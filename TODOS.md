# TODOS

## 2026-10-24 True-text frontier loop (plans/true-text-frontier-loop.md)

- [x] **I0b stage S5 (2026-10-28, working tree): the neighbour ink leg judges an in-show successor at its expected shifted position** (`_compensated_difference` in `test_scripts/true_text_acceptance_helpers.py`: a successor pixel counts only when it differs on the plain after render AND on the after page rendered with the compensating translation `-inshow_residual_pt` along the glyph's baseline through `frame.quarter_turn`, on the plain pixel grid; untouched glyphs keep the plain comparison; one render per distinct shift, none when the plain renders agree in the box; new non-report measurement `inshow_glyphs_ink_checked`, `NEIGHBOUR_REPORT_KEYS` unchanged). Red first: the rederive Q12 pin flipped to None at unit 2, `test_neighbours_ink_leg_compares_a_shifted_successor_at_its_expected_position` (units 1/2 x rotations 0/90/180/270); review fix-ups: stationary ink inside a successor box (rule, underline; the first cut failed it), turned text matrix, fractional page size (edge strip), render count, negative residual; swapped-successor guard (`(FE)`: `gid_mismatch` + `ink_changed`). Known residual risk: MuPDF sub-pixel glyph bins under float32 noise of the compensated pen (undetectable except by the report-churn gate). Refuter leftovers (owner calls, fail-closed today): an untouched glyph box overlapping a successor's re-rendered ink still flags on the plain render as in S4 (an AND for untouched glyphs would close it); the position leg is blind to a NaN residual (`nan > tol` is False; `_inshow_expectation` never produces one today). Gate numbers in the I0b plan log.
- [x] **Round 3 validator fix (2026-10-28, after 0481efe): `CANARY_KSIGN` joins `SYNTHETIC_CLASSES` in `scripts/evidence_bundle.py`** so the brief v6 (ac) synthetic second site validates while hvac is present (the full batch `20261028_0442_r2` was refused `synthetic_kind` on exactly that row; red test `test_v6_a_synthetic_ksign_canary_is_admitted_beside_the_hvac_site`, five-class guard, brief v6 §11 (ah) erratum, PITFALLS entry). Twelve older batches re-validate byte-identically.
- [ ] **Follow-ups the KSIGN admission leaves open (owner decisions, both tightenings):** (1) pin the synthetic KSIGN row's `synthetic_builder.kwargs` to `CTRL_SYN_KWARGS` the way `synthetic_pin_mismatch` pins the CTRL_SYN rows (brief v6 (ac) places the site on the CTRL_SYN_T1 page; the admission does not check it); (2) make the second KSIGN site R0-required (`calibration_incomplete` when a hvac-present batch has no synthetic KSIGN row). Brief v7 §2.3 reads the synthetic set as {CTRL_SYN_T0, CTRL_SYN_T1, CANARY_GROWTH, CANARY_KSIGN}.
- [x] **I0b stage S4 landed as df3ec65 (2026-10-28): `DEFAULT_ORACLES` in `scripts/evidence_rederive.py` is the six oracles (growth plus five adapters over the S3a/S3b helpers, `OracleContext.target_span` / `sink`, `remeasured.neighbours`), owner ruling Q2 in `emit_rows` (`_false_safe_owner`; `emit` refuses with exit 2), R16 (`_production_text_flags`) and the `python -O` refusal in the rederive CLI, the Q12 `/UserUnit` pin (`test_text_commit_oracle_twins.py`) and the Type0 `/W` pin (`test_text_commit_frontier_twins.py`).** Gate: 1114, 1713, 2116, 0948 and 1050 re-run with 0 comparator violations (only rows that reached the oracles changed; the validation reports are byte-identical). Next: review, then commit; the owner supplies a real `--planned`. Findings and follow-ups owed: (1) an experiment canary whose pen has no consumer is invisible to every oracle: CANARY_KSIGN (hvac p4 show 26, 0948 and 1050) passes all six (a standalone `Tj`; 0 of 188 later shows share its Tm; neighbours 0.0 / 0.0 / 0 / 104) and the validation `structure` phase is its only catcher (accepted by the lead, no special case); (2) FINDING, not tuned: the neighbour `ink_changed` leg does not exempt in-show successors that legitimately moved by the Q12 residual: pinned as an observation on a `/UserUnit` 2 page (a 0.2 px shift gives `neighbours: ink_changed: 2 glyph(s)` while the position legs pass at 3.7e-05 < 1e-4) and seen on the real F3 row `r2-F3-bdb495e9-p0-s49-grow1` (0948 and 1050: `ink_changed: 1 glyph(s)`, `max_inshow_dev` 2.857e-05; `emit` says `status_not_emittable` on both plans, its validated status is `probe_rejected` and the validator's `render_mupdf` phase fails it too); RESOLVED by I0b S5 (see the S5 line above); (3) `assert_wrapper_bytes_unchanged` cannot judge a multi-change row (`wrapper: unsupported:`; the helper models one splice and one delta, and only canaries have several changes today); (4) successor shows that share the pen, with fractional widths, are judged as untouched (exact) and can false-alarm; (5) texttrace origins are float32: at |x| > 512 pt a legitimate residual can exceed the 1e-4 tolerance (it fails closed: report it, never widen); (6) product slice rows (I3) must revisit the in-show expectation (`_inshow_expectation` judges every product row exactly); (7) every committed F30B, F30W and OUT row that quarantines as `oracle_assert_glyph_identity` (owner I1) carries EXACTLY the fixed `GLYPH_LEG_UNAVAILABLE` sentence (verified first-hand: all 5 such rows in each of 2116, 0948 and 1050, and 10, 13 and 13 experiment rows; the sentence does not say which unavailable shape applies: Type1, CFF, an unreadable program, ...): those belong to I1; (8) a real `emit` needs an owner-supplied `--planned` with `owned_until_slice` per class (the CLI default has none); setting an owner also turns that class's by-design guards into candidates; (9) the neighbour adapter's only vacuity rule is target ink (`neighbours: vacuous:`): a single-show page passes with the untouched, in-show and overlap legs unexercised; a later slice may add `glyphs_paired` to the sink with its own churn statement (`NEIGHBOUR_REPORT_KEYS` stays exactly the four X5 inputs, plan section 5). Plan: `plans/true-text-i0b.md`.
- [x] **I0b stage S3b landed (a8f961e, 2026-10-26): the byte-range, wrapper, count and glyph-identity helpers in `test_scripts/true_text_acceptance_helpers.py` (`page_streams`, `check_target_stream_changed_only_within`, `check_wrapper_bytes_unchanged`, `check_show_and_operator_counts_equal`, `glyph_identity_inputs`, `check_glyph_identity`, `IndependentLegUnavailable`), twins (i)-(v) plus three guards and the S3a twins' extended must-pass sets in `test_scripts/frontier_twins.py`, and the wiring into acc's commit test (range, wrapper and count per edit; reopened-stream equality; glyph identity per edited page, leg `cid_program_cmap` on all 14).** No finding on the historic fourteen. S4 (rederive consumption) followed (the line above). Follow-ups owed: (1) the Type1 (FontFile) and CFF/OpenType (FontFile3) glyph-identity legs raise `IndependentLegUnavailable`; the recipes are in the plan for I1; WinAnsi above 0x7E and `/Differences` encodings are unavailable too (I8 owns F31); (2) brief :2850 consistency (b) (the occurrence recompute) is NOT in `check_glyph_identity` (D4): I1; (3) CLOSED in S4: the rederive adapter rebuilds the ranges from `start`, `end_old` and the new operand's own length and never reads `end_new` (`test_stream_range_adapter_ignores_the_recorded_end_new`); (4) the cross-stream closing `EMC` branch of the wrapper check is unit-tested only (the product refuses that shape; PITFALLS); (5) PyMuPDF `get_fonts(full=True)` raises `TypeError` on a FontFile3 without a `/Subtype` (PITFALLS): audit the product callers; (6) `glyph_identity_inputs` and `check_glyph_identity` each take a `_measurement_copy` of the reopened document (hvac is 36 MB: two copies per edit, 28 per acc run for the 14 edits) and the check parses the program lazily (about 60 ms for the 3.5 MB CJK font); (7) the Type0 leg is the embedded program's own Unicode cmap (`cid_program_cmap`; a program with no (3,1)/(0,x) table raises `IndependentLegUnavailable`, U8, and A6 turns that into a failure for a positive); ToUnicode is only a consistency cross-check (`tounicode_disagrees`) because the product encodes through it. Measured on the five programs behind the historic fourteen: (3,1) present on all, 176 of 176 written glyphs resolve; (8) the ISO 32000-1 9.6.6.4 walk ignores `/Encoding` when the Symbolic flag is set, while MuPDF draws such a simple font through its (3,1) table: record for I1 so a real-corpus `unmapped` is not misread as a product defect. Plan: `plans/true-text-i0b.md`.
- [x] **I0b stage S3a landed (1fd42ec, 2026-10-26): the growth-zone and neighbour-glyph oracles in `test_scripts/true_text_acceptance_helpers.py` (`growth_zone_checks`, `check_growth_zone_was_blank`, `check_neighbour_glyphs_unchanged`, `EditedShow` / `edited_show`, `q12_inshow_residual_pt`), the ORACLE-twin runner and twins (vi)-(xii) in `test_scripts/frontier_twins.py`, `test_scripts/test_text_commit_oracle_twins.py`, rederive's `_growth_checks` as a thin wrapper, acc's agreement test and the wiring of both helpers into acc's commit test.** The agreement test is green on the historic fourteen in both shapes (applicable `{hvac/p4/show26}`), and the wired growth and neighbour checks are green on all 14 (no finding). S3b followed. Follow-ups owed: (1) `growth_zone_checks` extracts the rawdict (default flags) BEFORE it renders the 96 dpi pixmap on the same copy (moved verbatim so report bytes stay put); S4 did NOT reorder it (D11): a reorder changes acc, the twins and rederive at once, and its churn (render poisoning, PITFALLS) would have landed on class (a) rows next to R16 and made "nothing else moved" unprovable, so it stays its own micro-stage with a red test on an image-backed target; (2) CLOSED in S4: the `/UserUnit` factor of `q12_inshow_residual_pt` is pinned (`test_q12_residual_predicts_the_in_show_shift_on_a_user_unit_page`), MuPDF integerises a Type0 `/W` and `/DW` width like a `/Widths` entry so the Type0 residual is NOT 0 (`test_q12_mupdf_integerises_type0_w_widths`), and a None width maps to `INSHOW_SUCCESSOR_LIMIT_PT` (`test_neighbour_adapter_fails_closed_on_an_unprovable_width`); (3) a `2 Tr` show is emitted twice by MuPDF: the neighbour pairing treats each emission as a run but that shape, and annotation glyphs, are untested; (4) `ink_not_landed` fails closed on legitimate glyphs whose ink lies outside their metric box, zero-width boxes and white text, and FAILS OPEN when other ink (an overprinting glyph, a rule, a fill) sits inside a new glyph's metric box, because the mode-colour rule only asks whether the crop is non-uniform; the leg catches twin (xii) only; S4 idea: count the pixels of the span's own fill colour (texttrace `color`) in the crop, or diff the crop against a render with the target show removed; (5) the `overlap` leg is strict positive-area on 1 em boxes and is unmeasured on tight-leading real pages beyond the historic fourteen; (6) design :166 still says "+-3 pt halo" (superseded by owner Q1: 2 pt + one pixel of slack); (7) CLOSED in S4 (R16): `_production_text_flags` pins `small_glyph_heights` ON in the rederive CLI (`test_cli_rederives_under_the_production_text_flags`); no report row changed. Plan: `plans/true-text-i0b.md`.
- [x] **I0b stage S2 landed (9ced903, 2026-10-26): `test_scripts/simple_font_fixture_builder.py` (seven FontBuilder TrueType kinds, fractional `widths`, `overhang`), `test_scripts/frontier_twins.py` (`TwinSpec`, `OracleTwinSpec` shape, `TWINS`, `ORACLE_TWINS = ()`), `test_scripts/test_text_commit_frontier_twins.py` (CI lane), plus the D-2 pin (`_trace_for` == rederive `_locate_trace` on the historic fourteen) and the R16 measurement in `test_true_text_frame_parity.py`.** Observed at HEAD (the reds later slices inherit; the call shapes bare `expected_origin=None` and located origin+box agree): `tounicode_lie` and the nameless `symbolic_post3_wrongglyph` COMMIT as Tier 0 with the B outline (texttrace gid 35; I1's G1' reds); `symbolic_wrongname` is refused `verification_failed` only because MuPDF extracts a glyph's text from its name (the reason must flip to `font_builtin_encoding_unproven` in I1); `symbolic_ascii` is REFUSED `encoding_failed` (design :203 expected COMMITTED; a face with no Unicode cmap has no active charmap, so `has_glyph` is 0); `winansi`, `post3_cmap31` (F30W) and `symbolic_post3` (F30B guard) commit Tier 0 with gid 34. Twin (xii) IS buildable: a plain rectangular clip that hides the last growth glyph's ink is refused `verification_failed`, but a gap clip (two rectangles, bounding box over the glyph, area missing its ink) commits Tier 1 and leaves the glyph with 0 ink pixels (measured for one clip shape). (vii) frame stroke, (ix) overhang growth with and without the trailing space, (xi) Tf 6 commit Tier 1. MuPDF integerises an x.5 `/Widths` entry half UP after parsing the real as float32 (S4's residual is `floor(float32(w) + 0.5)`, never Python `round`). R16: texttrace boxes are `small_glyph_heights`-independent, rawdict boxes are not (619 of 3161 on hvac p4), so S4 pins the flag ON in the rederive CLI. Next: S3a. Plan: `plans/true-text-i0b.md`.
- [ ] **Follow-up after I0b (plan D-2): unify acc `_trace_for`, rederive `_locate_trace`/`_locate_target` and `frame_prepare` into one locator** (V12 sub-range and V13 positional need the rederive form). Until then `test_trace_for_and_locate_trace_agree_on_the_historic_fourteen` pins the two as bit-identical on the whole-show historic rows.
- [x] **I0b stage S1 landed (2026-10-26): acc's oracle code moved to `test_scripts/true_text_acceptance_helpers.py` with H3 (`frame.base` / `frame.quarter_turn`), `decode_show(font_kind=)` dispatch, a lexer-based TJ-compensation check, a font-kind-aware source-font check, `can_encode_simple`, and acc's `prepared.tier == case.expected_tier` assertion.** The pixel-mask halo is the product's `_HALO_MARGIN_PT` (2 pt, Q1) built by one `halo_mask`, with one pixel of raster slack in `_assert_pixels_changed_only_inside_masks` and one `RENDER_ZOOM` scale; the Poppler finding (ecc p0, 6 pixels 2.05 pt out, UI umbrella 19 of 21) is resolved by that slack, not by a wider pt pad (PITFALLS entry). Same-class H3 sites fixed in the UI umbrella, `source_show_commit`, `source_run`. Locks: `test_true_text_acceptance_helpers.py` (pure) and `test_true_text_frame_parity.py` (bit-identity on the historic fourteen, ten rotated). Next: S2 (simple-font builder, twins skeleton). Plan: `plans/true-text-i0b.md`.
- [x] **I0a landed (2026-10-26): stages 1-2 d7c6483/2583e55; stage 3 (acc literals deleted, acc re-exports the loader, `evidence_bundle` imports the loader's `CALIBRATION_STRINGS`, rederive acc leg and `--no-acc` removed, parity module renamed `test_true_text_corpus_fixture_digests.py`) in the working tree, uncommitted.** Still open: the UI shard factory `true_text_ui_shard.py` is deferred to the first shard (no frontier row is `active` yet; the umbrella's 19-function pin stays); `test_text_commit_real_corpus_refusals.py`/`_candidates.py` wait for the first ingested rows; the six oracle helpers are I0b (the `expected_tier` assertion in acc landed with I0b S1). Plan: `plans/true-text-frontier-loop.md` log 2026-10-26 I0a stage 3.
- [x] **UX gap (owner IME test 2026-10-26): a paragraph target whose line is two show operators in two fonts (Latin run in one Type0 font + CJK run in another, zero gap) is refused by the preview binder as `no_source_match` ("找不到這段文字在 PDF 中的原始內容"), although the commit side has the accurate code `multi_span_target` ("一次修改多段文字（段落）需要重建文字"). The user reads the message as a glyph problem; run mode on the CJK run commits the same content at Tier 1. Fix shape: when the resolved paragraph has more than one run (or runs in more than one font resource), the preview reports `multi_span_target` before binding. Second finding of the same test: widening the 3-glyph Latin run is refused `growth_region_not_blank` because the CJK run starts 0.005 pt after it; correct by design (no-jump), but the refusal text could add "edit the neighbouring run instead". Red test first (preview on a synthetic two-font line), then `view/text_edit_reasons.py` / preview; no engine change. **Landed uncommitted (2026-10-26, round 8): `_tier0_target_from_resolve` returns None for a run-join target whose member runs carry more than one `font` (a show selects one font, so no single show can carry the line); the commit side now says `multi_span_target` and the preview `target_unresolved`, which the paragraph-mode view remaps to the same text. Tests: `test_scripts/test_paragraph_multi_font_target.py` (+ `test_f3b_*`; `test_f3_*` moved to a colour break). The `growth_region_not_blank` wording is left as is: its detail only counts occupying characters and names no neighbouring run, so a "edit the next run" hint cannot be tied to the cause.**
- [ ] **R8-1 leftovers (2026-10-26):** a multi-show line in ONE font (colour split, or two same-style shows merged into one index run, e.g. `(To) Tj (tal) Tj`) still refuses as `no_source_match` in paragraph mode, and two shows in two fonts whose text the index merges into ONE run, or two font resources that report the same font name, are not seen by the font check (the check compares `EditableSpan.font`); a show-count signal from the source grouping (not the run `font` name) would cover both. Not owner-reported, not changed. The multi-font rule is paragraph-only by design (the view's remap is): run mode (S17 joined boxes) and the tier-funnel census keep HEAD's outcome. A save that loses the session (`SaveRecoveryError`) during the new save-first close branch turns the tab into a dead tab and discards the refused input with the editor (not pinned by a test).
- [x] **CLOSE-PROMPT-1 (owner IME test 2026-10-26, save/reopen step): the document was already saved (Ctrl+S, tab `*` cleared) and the inline editor still held refused input (`原字型沒有這個字`); the tab close prompt said `有尚未套用的文字編輯或未儲存的變更` and offered `儲存後關閉`, which cannot do what it says: `_finalize_inline_editor_for_close(save=True)` keeps the editor (`_CLOSE_KEPT_NOTICE`) and the close is aborted, read by the owner as a failed save ("缺乏子集無法存檔"). `放棄變更` then closed and the committed edit was on disk, so no data was at risk.** Fix shape: in `PDFController._confirm_close_session`, when `session_has_unsaved_changes` is False and the editor reports a rejection reason, say `編輯框內的文字無法套用（原因）；關閉會捨棄這段輸入` with 捨棄並關閉 / 取消 (no `儲存後關閉`); when the document is also dirty keep the three buttons but state that the refused input is dropped by `儲存後關閉`. Red test on the prompt text/buttons first (`test_scripts/` close-prompt tests), no engine change. Minor, same run: the status bar still read `已修改` after the save while the tab title had dropped its `*` (status bar refresh after Ctrl+S; verify before fixing). **Landed uncommitted (2026-10-26, round 8): one policy for the tab close and the window close. Clean document + refused input: title `無法套用的文字編輯`, text `編輯框內的文字無法套用（<原因>）；關閉將捨棄這段輸入。`, buttons 捨棄並關閉 / 取消 (default), N=捨棄. Dirty document + refused input: the three buttons stay, the prompt adds `「儲存後關閉」會先捨棄編輯框內無法套用的文字，再儲存文件。`, and the button saves first, then drops the input (a cancelled Save dialog keeps tab, editor and input). Verified and composing input keep today's prompt. `test_tab_close_save_with_refused_input_keeps_the_tab` and `test_window_close_save_all_with_refused_input_aborts_the_close` pinned the old policy and were rewritten. The status bar now refreshes inside `PDFView.set_document_tabs` (red-first: it kept `已修改` after Ctrl+S).**
- [x] **Brief v5 enforced landed, uncommitted (2026-10-26): one runner per batch, positives-only single_family, office-report-23p registered.** From batches `20261026_0015_r2` (pilot, pass) and `20261026_0032_r2` (full, 61 cases, pass; two-run composite undetectable under v4). Schema enum 5 + `code_revision.runner_sha256`; `RUNS.json` last-entry rule; six batch-level `runner_*`/`runs_*` codes; `recompute_parent_summary` positives-only lineages and families at rev >= 5 (one flag per batch); `schema_additional` for `runner_sha256` on rev <= 4; `_evidence_pilot/**/*.py -text`; acc-leg duplicate-sha guard; manifest row for office-report-23p (local file renamed to `test_files/office-report-23p.pdf`); `plans/grok-briefs/brief-v5.md` (section 10 (w)/(w2)/(x)/(x2)/(y)/(z)/(aa)). Gate: 491 + 239 tests, ruff clean, five batches validate byte-identical, 0032 rederive 24/35/1/1 (only the F2I census row stays `reason_order`). Open: D22 (V15 predicate excludes census rows: owner call), D18 X5 after I0b, part 5 closure before I0a, F2K stays open (decisions 1-2).
- [x] **V12 triage of the 28 rederive quarantines of batch 2116 (2026-10-25, design only).** `plans/v12-quarantine-triage.md`: 15 contract ambiguity, 8 rederive gaps, 5 provenance pending I0a, 1 Grok slug defect, 0 product. Owner accepted Q1–Q8 per recommendation (rev≥3 reading for rederive only, `measurement_only` flag for F2R/F2G, font_kind by /Subtype, nullable geometry under origin_reliable=false, reason-only fallback with uniqueness guard, hash-register the I0a files, `before_pdf_mismatch` rename deferred). Implementation V12–V16 in progress.
- [x] **V12 part 1 landed, uncommitted (2026-10-25): target granularity (rows #1-12).** Brief revision 4 (`plans/grok-briefs/brief-v4.md`, v3 untouched; carries only the V12 text so far, V13 and V16 add theirs), `_rev(case) >= 3` replaces every `== 3` gate, schema `show_text_sha256` + `probe.whole_show_max_tier_1`, validator `item_range_bounds` / `item_range_span` / `show_text_sha256_required` / `_mismatch`, rederive `_derive_target` + sub-range locate + slice probe + whole-show second view + slice F3 advance, `measurement_only` (F2R, F2G) in `emit_rows`. 2116 rederive: quarantined 28 -> 16 (rows #1-11 `deferred`, #12 `rederived`); 1114 / 1713 / 2116 validate byte-identical, 1114 / 1713 rederive differ only in `date_utc`; 48 new tests (41 red first, 5 locks, 2 mutation-red). Open: V13 locate failures / `font_kind` / nullable geometry, V14 canaries, V15 `reason_order`, V16 provenance (`relative_path_required`, `slug_not_derived`, I0a registration); validator does not yet require `probe.whole_show_max_tier_1` on slice rows; the `_row` manifest keys `show_text_sha256` / `item_range` / `byte_range_in_item` need a consumer decision when I0b lands.
- [x] **V13 landed, uncommitted (2026-10-25): locate failures, `font_kind`, untracked-origin geometry (rows #16-18).** `target_unlocatable` quarantine (a locate miss is never a product `exception` and is never compared with the record), one shared `_locate_target` (untracked origin -> not located; text; positional for U+FFFD / private-use anchors, `remeasured.locate_method`), reason-only fallback probe for census / negative rows with null geometry and a unique target show (`remeasured.probe_fallback`, `geometry_unverifiable` finding in `emit_rows`), `font_kind` from `/Subtype`, `geometry_on_untracked_origin`; schema geometry nullable from brief v4, validator `geometry_*` codes (rev 4), brief-v4 text (M1 untracked origin + positional, 5.1 font_kind, section 9 (q)). 2116: see the loop plan log; 1114 / 1713 byte-identical. Open: V14, V15, V16; the positional anchor checks only the first glyph; the validator does not cross-check `limits[]` for `locate_method: positional`; a codec-less Type0 F2/F3 slice still decodes latin-1 (unit 1) in `_derive_target`.
- [x] **V14 landed, uncommitted (2026-10-25): canary remeasure (rows #13-15).** rederive only: one operand selector (`_operand_index` / `_operand_change`) for `_old_new_codes`, `_first_change_old` and the K read, `canary_changes_shape` for any other multi-change canary shape, after-locate anchored on the located before-origin with the 0.02 pt gate plus a positional fallback (`_locate_after`, plain min/max glyph union), `after_text_identity` observation (divergence off CANARY_FONT / CANARY_WRONGGLYPH), brief-v4 clarifying row (r). 2116 rederive: quarantined 15 -> 12 (TC, FONT, WRONGGLYPH -> `deferred`); 1114 / 1713 validate byte-identical, rederive differ only in `date_utc`; 14 new tests (11 red first, 2 locks, 1 mutation-red). Open: V16.
- [x] **V15 landed, uncommitted (2026-10-25): `reason_order` predicate (rows #19-20).** rederive only: the check moved after `_Scene` is built and exempts only the recomputed whole-show negative twin (`sha256(scene.text) == original_sha256`, mutation null, kind negative, `byte_range_in_item` null; `_is_whole_show_negative`); no scene, no exemption. Design doc lines (rederive paragraph, rejection list, R3-1 row) and ARCHITECTURE vocabulary amended. 2116 rederive: quarantined 12 -> 10 (both twins -> `rederived`, subject to the X5 hold); 1114 / 1713 validate byte-identical, rederive differ only in `date_utc`; 3 new tests (2 red first, 1 fail-closed lock). Open: V16.
- [x] **V16 landed, uncommitted (2026-10-25): provenance and registration (rows #17, #21-28).** Validator `relative_path_required` and `slug_not_derived` (rev >= 4, shared `_slugify`); I0a registration: four public files in `public_corpus_sha256.json` (19 now), the four `local_unrecorded` files in the new minimal `test_scripts/fixtures/true_text_corpus/manifest.json` (`corpora` only; the design's `cases` / `ui_shard` / hvac / ecc / office-report-23p stay with the rest of I0a), hashes recomputed from disk; `load_registry` manifest leg (`--manifest`); `before_pdf_mismatch` meaning documented (rename deferred, Q7); brief-v4 section 9 (s) plus the collected list of what the next paste tells Grok. 2116 rederive quarantined 10 -> 4 (#17, #21-25 resolve; #26-28 are measured and stay quarantined for the V13 reasons). 1114 / 1713 reports unchanged. Open: the five dotted-slug veraPDF PDF/UA rows and `isartor-manual` of 2116 would fail `slug_not_derived` at rev 4 and are not registered public files; a rev-4 Grok run must derive their slugs.
- [x] **Q9 decided (2026-10-25): owner accepted gating V16 `relative_path_required` / `slug_not_derived` at brief_revision >= 4** (memo said >= 3; rev 3 would turn 2116 rows #23, #25-28 into validator rejections instead of registered measurements).
- [x] **V12-V16 review fixes landed, uncommitted (2026-10-25).** (1) the X5 hold is on the class: F2R/F2G stay held for a list plan, an empty entry and `--planned` JSON, only `measurement_only: false` lifts it; (2) validator `whole_show_view_required` (rev >= 4, slice target needs a non-null `probe.whole_show_max_tier_1`); (3) `_glyph_unit(cap)` keyed on `/Subtype` at all four sites; (4) brief-v4 `item_range_span` / `show_text_sha256_*` say `brief_revision >= 4`, matching the code.
- [x] **Brief §5.2 `background_bbox_visual` on a slice target (found by the V12-V16 review round 2):** the quad `(0.0, -0.35*Tfs, adv_old_text_space*Th, Tfs)` starts at the show origin with width `adv_old`, so for a `string_fragment` / `fragment_split` / `tj_item` target that does not start at the show start the background strip covers the prefix glyphs, not the slice; the product's `_build_tier1` has the same input for a whole-show target only. 2116 DID exercise it: two F2G `tj_run` rows (`f17a0919-p0-s4-grow1`, `f723638d-p0-s0-grow1`) carried the origin-based quad ~393 pt left of the target; the slice-origin quad matches `target_bbox_visual` x0 to ~0.03 pt; they flip deferred -> quarantined(remeasure) (2116 rederive with Q10 alone: 20 rederived / 29 deferred / 8 validator_rejected / 1 skipped / 6 quarantined, from 20/31/8/1/4; 1713 identical). Q10 decided (2026-10-25): slice-origin quad, x_pre = prefix advance incl. kerns; rederive + brief v4 (t). Q11 decided (2026-10-25): width includes inner kerns, K_inner; 2116 → 20/28/8/1/7 (third row: F2R `bdb495e9-p0-s2-eq1`, slice [0,2], K_inner 27, new x1 within 0.002 pt of `target_bbox_visual`; 1114 and 1713 identical). Leading kern counts into x_pre for whole-show TJ.
- [x] **Brief v4 full run `20261025_1824_r2` triaged (2026-10-25, worktree, uncommitted).** HEAD 11c2a3e, 58 cases (14 R0 + 44 frontier), calibration pass (6 controls, 8 canaries caught), 0 runner errors; validate ok, 0 violations; rederive 21 rederived / 34 deferred (`oracles_incomplete`, I0b) / 0 validator_rejected / 1 skipped / 2 quarantined, 0 divergences. The dotted veraPDF slugs and `isartor-test-suite-manual` derive correctly; the three Q10/Q11 slice growth rows are `deferred` (no `remeasure`); F17 `1017c455-p0-s1-cen1` now rederives through the reason-only fallback. Quarantines: F1 `4a3bf064-p0-s5-eq1` `provenance_unverified` (PDF/UA-2 `8.2.5.20-t02-pass-a` was not in the sha table; registered now with lineage `vera-ua2-8-2-5-20-t02-pass`, hash recomputed from disk, red test first; rederive with the new list -> `deferred`, 21/35/0/1/1) and F17 `faefb744-p0-s28-cen1` `target_unlocatable` (V13 by design: untracked origin, Type3, four shows spell the target; Q13). Grok's README caught that brief §5.1 growth_zone still quoted the pre-(t) quad; rewritten to the (t) formula, row (t) and the V16 tell-Grok text amended.
- [x] **Q12 decided and landed (2026-10-25, worktree, uncommitted): the neighbours `inshow_successor` limit of 1e-6 pt is unattainable in MuPDF when `/Widths` are fractional.** 1824 rows F3 `f723638d-p0-s7-grow1` (0.00109 pt) and `bdb495e9-p0-s49-grow1` (0.00296 pt) are `probe_rejected` by the neighbours phase alone. MuPDF keeps simple-font `/Widths` as integers (the texttrace advance of `e` is 444 where `/Widths` says 444.4, `m` is 833 for 833.3), so a kern computed from the exact widths (K agrees to 1e-6) leaves the successor off by (sum frac(w_old) - sum frac(w_new)) * Tfs * Th * scale / 1000 (pin test: MuPDF rounds, so the residual is the rounding-difference sum sum_new(round(w) - w) - sum_old(round(w) - w), at most 0.5 unit per glyph; the one-unit bound keeps a 2x margin): 0.1 * 10.9091 / 1000 and 0.3 * 9.9626 / 1000, the two observed values to float32. Equal-advance permutations cancel it (the F2R rows on the same fonts measure 0.0), so T16-4X P-B's 0.0 was a special case. Recommendation: validator bound `(char_count_old + char_count_new) * Tfs * Th * trm_scale / 1000 + 1e-6` from recorded fields; rederive recomputes the exact residual from `/Widths` (pin truncation vs rounding with a red test on a 500.7 width) and compares at 1e-3; brief §5.2 neighbours sentence; PITFALLS entry; every revision (1114, 1713 and 2116 have no such row). Landed: `evidence_bundle._inshow_successor_bound(case)` (rev >= 4 only, read from the first advance object and `target.trm_scale`, fail closed to 1e-6) feeds `check_pairing`; `test_q12_*` in the contract file, including `test_q12_mupdf_integerises_fractional_widths` (MuPDF rounds to the nearest unit: 600.7 -> 601, 600.4 -> 600, not truncation); brief v4 section 5.2 line and row (u); PITFALLS entry; the exact-residual recompute from `/Widths` in rederive stays with I0b. Re-validating 1824, `f723638d-p0-s7-grow1` and `bdb495e9-p0-s49-grow1` each get `phase_result_mismatch` (neighbours recorded fail, recomputed pass) and `status_mismatch` (recorded probe_rejected, recomputed insufficient_evidence) until a fresh run; 1114, 1713 and 2116 validate byte-identical.
- [x] **Q13 decided and landed (2026-10-25, worktree, uncommitted): reason-only fallback when the product itself answers `ambiguous_source_match`.** F17 `faefb744-p0-s28-cen1` stays `target_unlocatable` because four shows spell the target and V13's uniqueness guard refuses the fallback. With `expected_origin=None` the product binds by text alone, and `ambiguous_source_match` means it bound to nothing, so that answer does not depend on which show the record meant. Recommendation: allow the fallback when the record's show is among the spellings and accept only a product rejection with reason `ambiguous_source_match`; any prepared or other result under a non-unique spelling keeps the quarantine. Landed: `_fallback_probe_ok` returns `"unique"`, `"shared"` or None; a shared spelling is probed with `expected_origin=None` and accepted only as a `PlanRejection` with reason `ambiguous_source_match` (`probe_fallback = reason_only_shared`), any other answer keeps `target_unlocatable`; `test_q13_*` (V13's uniqueness test became `test_q13_a_shared_spelling_is_accepted_only_as_ambiguous_source_match`); ARCHITECTURE and brief row (v). 1824 rederive: F17 `faefb744-p0-s28-cen1` quarantined -> rederived (22 rederived / 33 deferred / 2 validator_rejected / 1 skipped / 0 quarantined; the two validator_rejected are the Q12 F3 rows); 1114, 1713 and 2116 rederive identical.
- [ ] **Owner-visible decision (V16 gate):** the triage memo said `relative_path_required` and `slug_not_derived` apply at `brief_revision >= 3`; the code gates them at `>= 4` because at rev 3 rows #23 and #25-28 of batch 2116 would become validator rejections instead of measured rows. Needs the owner's yes (or a switch to `>= 3` plus re-validating 2116).
- [ ] **Product observation (V12 Q8):** on `r2-F3-bdb495e9-p0-s49-neg1` the product PREPARED a Tier 1 edit (and rederive's replay committed it) when asked to replace a whole item with a one-glyph string via a whole-show target. Engine works as designed for a whole-show target; the F3 negatives will systematically show it. No product change; keep in mind when reading F3 negatives.
- [x] **V11: a plan-row schema violation is scoped to the citing cases (2026-10-24, worktree, uncommitted).** `check_pre_registration` → `_scope_plan_violations`: a `/cases/<i>` violation on a frontier-class row is attributed to every case with that registration key (row still registers); an uncited frontier row is unverifiable `plan_row_invalid`; R0 rows, non-frontier rows and plan-level pointers stay batch-level; `_plan_row_key` scalar guard removes the `check_error` on list/dict key fields. Brief v3 change (o) + §5.1 slug rule (= rederive `_slugify`), closed variant vocabulary (`grow` = advance changed), §3.4 shrinking `fragment_split`, §1 five file types. 2116: 8 plan violations now carry case ids, rederive runs (8 rejected / 12 rederived / 15 deferred / 28 quarantined / 1 skipped); 1114/1713 identical. PITFALLS "A malformed frontier plan row".
- [ ] **Rederive: refuse when any `validator_rejected` case has kind control or canary** (pre-existing class gap found by the V11 refuter: `check_calibration` ignores violations, so a rejected R0 case still yields calibration "pass"). Tightening, gate on `brief_revision == 3`; 1114/1713/2116/1803 unaffected.
- [ ] **Validator: registered-but-unrun plan row** (`plan_row_unrun` unverifiable, gate on rev 3): 2116 row 21 (F30W isartor-6-5-3-t01-fail-a, runner `AttributeError`) left no trace.
- [x] **I0c landed: validator + rederive (2026-10-24, working tree).** `scripts/evidence_bundle.py` + `scripts/evidence_schemas/*.v2.schema.json` + `scripts/evidence_rederive.py` + `test_scripts/fixtures/public_corpus_sha256.json` + `test_scripts/test_evidence_bundle_contract.py` + `test_scripts/test_evidence_rederive.py` (no `model/` change). Follow-ups: I0a registers local_unrecorded/office-report-23p in manifest `corpora` (until then they quarantine); I0b replaces `DEFAULT_ORACLES` (unifying `_trace_for`/`_locate_trace`/`frame_prepare` is a follow-up after I0b, plan D-2); fixed in Part B: `product_advance_mismatch` is Tier 1 only (a Tier 0 `PreparedEdit` carries no advances). Fix round 1 (review + forger findings) closed R0 completeness, null-K and fabricated-`K_sum` forgeries, lineage inflation by sha, the digested-id CLI filter, experiment rows emitted after a partial remeasure and `emit_rows` ignoring the recomputed status; fix round 2 (review + forger findings, 2026-10-24) closed the duplicate-control R0 blind spot and the pinned control sites, `synthetic_only` while hvac is measured, the self-reported halo/ink/target-run/is_space flags, the Tz association order in the growth oracle, ParentTree nulls, the F3 `item_range`, the validation-to-batch tie and the unverifiable-is-not-ok report key; still open: the 2x/6x renders, ink-landed leg, neighbour pairing and glyph gids stay unmeasured until I0b (experiment rows are `deferred` until then); owner decision on `scripts/hooks/__init__.py`. ARCHITECTURE 16; PITFALLS "A bundle's status words and numbers are claims".

## 2026-10-22 test-suite-never-hangs (plans/archive/test-suite-never-hangs.md) -- all phases landed, CI hang drill done 2026-10-23

- [x] **Whole-suite runs never hang unresolved.** `scripts/run_suite.py` (external supervisor, per-file Qt interpreters, heartbeat
  stall kill, `--deselect` rerun, merged junit, one summary line) is the only sanctioned whole-suite command locally and on CI;
  `pyproject.toml` adds `faulthandler_timeout = 540` + `faulthandler_exit_on_timeout = true` as the in-process first line.
  PITFALLS "In-process watchdog exit deadlocks in ExitProcess"; ARCHITECTURE 7.4; tests in `test_scripts/test_run_suite.py`.
- [x] **Phase 2 leak guards** (2026-10-23, separate commit): `scripts/pytest_leak_guards.py` (loaded from `test_scripts/conftest.py`) fails the
  leaking test itself for a visible top-level `PDFView`/inline editor, an unfinished `QThread` or an unexpected `QMessageBox`/`QDialog.exec`
  (recorded AND raised, so a call swallowed inside a Qt slot is still red); `real_modal` marker for the 4 tests that need a real `exec`.
  PITFALLS "A leaked PDFView, QThread or modal dialog fails a LATER test"; ARCHITECTURE 7.4 (6); tests in `test_scripts/test_leak_guards.py`.
- [x] **Shrink the leak allowlists to empty** (2026-10-23): the four GUI modules (`test_text_commit_apply_by_token.py`, `test_text_commit_no_silent_legacy.py`,
  `test_text_commit_plan_preview_no_css.py`, `test_text_edit_rotated_page_gui.py`) replaced their pre-dispose teardown with
  `qt_teardown.dispose_pdf_view(view, controller, model)` (four sites, one per module); `_KNOWN_GUI_LEAKERS` is `frozenset()` and `test_leak_guards.py::test_plugin_public_names`
  pins both lists empty, so a new leaker is fixed in its teardown, never listed.
- [ ] **Widen the modal guard's entry points** (S4-P2-08, noted 2026-10-23): `GUARDED_MODAL_CALLS` covers only `QMessageBox.exec/information/warning/critical/question`
  and `QDialog.exec`. Production code also reaches real modals through `QMessageBox.about`, `QInputDialog.getText/getMultiLineText`, `QColorDialog.getColor`,
  `QMenu.exec_` and the `exec_` aliases; the C++ statics run exec internally, so patching `QDialog.exec` from Python does not intercept them and an unpatched
  test reaching one still ends only by the runner's stall kill. Needs a spec change (not a quick edit of the tuple).
- [ ] **Flaky: `test_print_subprocess_helper::test_run_print_helper_emits_heartbeat_during_long_submission`** failed once in the
  2026-10-23 Phase 2 gate run (`assert event_types[-1] == 'succeeded'` saw a trailing `heartbeat`): the helper's heartbeat thread can
  emit after the final event. No Qt, passes alone; fix the ordering in the helper (stop the heartbeat before emitting the result),
  red-light first. See plans/archive/test-suite-never-hangs.md log S6-5.
- [x] **CI hang drill** (2026-10-23, scratch branch `scratch/ci-hang-drill`, runs 39900746891 baseline / 39904164827 drill): the windows leg
  reported `test_ci_hang_drill.py ... HUNG 540.8s`, named `test_hangs_forever` in the junit, reran the file OK and exited 1 in 51 min 37 s;
  junit uploaded. The evidence artifact was empty (`.run_suite/` is hidden); with `include-hidden-files: true` the third run (39912583129)
  uploaded 274 files incl. `evidence/test_ci_hang_drill.heartbeat` + `.tail.log` (faulthandler dump, culprit in flight). Step 57 min 44 s.
- [x] **CI step budget** (2026-10-23, owner): one hang costs ~10 min (540 s faulthandler exit or 600 s stall + rerun) and the windows
  functional step takes 36-40 min clean, so the drill used 51 of 60 `timeout-minutes`; raised to 90 (two hangs, or a hang in the pure
  job with its whole-lane rerun, now fit). Open half: lowering `--stall-seconds` / `faulthandler_timeout` on CI needs a per-test maximum
  first (one CI run with `--durations`), otherwise a slow runner turns a legitimate test into a HUNG; CI now passes `--file-ceiling 1800` (pure lane peaks 1217 s),
  so a ceiling kill fits the 90 min step with a junit.
- [ ] **CI-speed timing thresholds fail on windows-latest:** `test_text_commit_replay_fast_path::test_pathological_inputs_stay_linear`
  (`[malformed-cm-blocks]` 4.12 s and 5.72 s, `[deep-unclosed]` 4.45 s, limit 4.0 s) and `test_text_commit_click_latency::
  test_page_fingerprint_of_an_annotation_heavy_page_is_fast` (295 ms, limit 250 ms) in the 2026-10-23 drill runs; the blocking leg
  cannot go green until they are relaxed on CI or made relative. ubuntu (advisory) also has 13 failures: Windows-path assumptions in
  `test_user_preferences` / `test_security_subprocess_paths`, RSS bound in `test_text_commit_lexer_streaming`, ext-B font absent,
  `test_single_instance_forwarding`, two rotated-caret cases in `test_text_commit_editor_mouse_gestures[270]`.
- [ ] **Layer-boundaries CI job is red on a docstring:** the `threading.Thread` grep over `view/` hits the comment at
  `view/ext_b_subset_worker.py:11` ("`threading.Thread` is banned in `view/`"); reword the docstring (or exclude comments in the grep).
- [ ] **pip-audit (blocking) is red:** pillow 12.3.0 has 35 known CVEs, fix version 13.0.0; bump `requirements.txt` / `constraints-ci.txt`
  after checking PyMuPDF / surya compatibility.
- [x] **py-spy** (2026-10-23): installed on the dev machine (0.4.2, found via PATH); CI installs `py-spy==0.4.2` in its own step
  before the functional suite (continue-on-error, evidence-only). Not yet seen producing a dump on a real CI hang: check the next
  drill's `*.pyspy.txt` (ubuntu may need ptrace permission).

## 2026-10-21 w1b fix round -- found; all but the last fixed 2026-10-21

Found in the w1b /simplify review and in its fix round:

- [x] **`utils/file_share_lock.py` same-thread hardening.** A drop that reached the registry on the thread already
  inside a registry call (a garbage-collection `weakref.finalize` drop, or `PDFModel.__del__` -> `close()` ->
  `release()`) re-entered the `RLock` and ran mid-operation; at the `suspended()` exit and in `ensure()` a drop of the
  last claim during the re-open left the new deny-write handle on a removed entry (file write-locked, `is_locked()`
  False). Fixed: every drop is queued and the outermost registry call on the thread (`_registry_call`, depth 1)
  applies the queue before it starts and before it lets go; still an `RLock`, so an explicit `release()` on the owning
  thread never deadlocks. Four tests in `test_scripts/test_session_file_share_lock.py`. PITFALLS: OD-FS1-LOCK
  ("On Windows another program could rewrite the open session's file ...", same-thread rule).
- [x] **`restore_stream_storage` rewrote a stream dictionary whose names hold a literal backslash-u escape.** Fixed
  with the other places that wrote `xref_object` text back: `utils/pdf_object_source.xref_object_exact` reads an
  object's source undecoded, and `model/` and `utils/` read with it (the stream-storage restore and the patch revert,
  the annotation dictionary restore, the page-graph snapshot, the protected-page rollback and its fallback, the
  signed append save's replay, `navigation_graft._load` with `page_refs`, the inherited-resources copy of the
  paint-state writer, the new-font-stream dedupe, the `/Annots` appenders; the text-commit object reads as
  hardening). `xref_object` stays only in reviewed whole-document walks. `test_scripts/test_exact_object_text.py`
  (55 tests at the time, with an allowlist guard). PITFALLS W1B-DICT-RT.
- [x] **`xref_set_key` renamed a name that holds a literal backslash-u escape anywhere in the object it edits.**
  Fixed 2026-10-21 (owner: an exact set_key as the one entry, plus a guard). `utils/pdf_object_source.py`
  `xref_set_key_exact` is PyMuPDF 1.27.1's `xref_set_key` with the decode taken out (same checks, exceptions, MuPDF
  calls and quirks; 147,692 dictionary objects of the corpus, a key added and nulled on each: none differ; the
  placeholder quirk went 2026-10-22, next item), and
  `exact_set_key(doc)` routes PyMuPDF's own methods that call it (`Annot.set_colors`, `Document.set_metadata`,
  `subset_fonts`, `Page.replace_image`, `embfile_add`). The 33 calls in `model/` use the helper and the 14 method
  calls run inside the block; two AST guards and a pin of PyMuPDF's callers in
  `test_scripts/test_exact_object_text.py`. PITFALLS W1B-DICT-RT.
- [x] **PyMuPDF's placeholder on a key path through an indirect dictionary: two user actions wrote a junk string.**
  Fixed 2026-10-22 (owner: fix it once in the exact set_key, for later callers too). `xref_set_key_exact` no longer
  prints the object: it parses the value alone (one PDF object, else it raises before any write), follows a level
  of the path that is an indirect dictionary and puts the value at the key, where `xref_get_key` reads it; every
  refusal comes before the first write. `xref_key_holder` names the object that holds the key. (a) Page straighten
  on a bookmark whose GoTo action is an object of its own keeps the bookmark's page and view. (b) Deleting an image
  nulls the name in a `/Resources` object of its own instead of writing the string, and keeps it while another page,
  form or tiling pattern that resolves the name in the same object still draws it, or a Type3 font uses that object
  (`_streams_resolving_the_entry` compares holders). Bookmarks sharing one action move together. Also gone: the placeholder at a key printed otherwise (`#`, non-ASCII, trailing slash) and after a
  value that does not parse, and keys added by a value of several objects. Tests in `test_exact_object_text.py`
  (deviation tests, a class guard over target kinds × key paths × values), `test_bookmarks_toc.py`,
  `test_native_pdf_images_model.py`. PITFALLS W1B-SETKEY-PH.

## 2026-10-08 True-text UI part 5 round 7 (origin patch, plan-mode chip retired, rotated-page grip move)

Fixed in round 7 (`plans/true-text-ui-part5.md` section 14, `docs/ARCHITECTURE.md` section 10.2,
`docs/PITFALLS.md`): the original text showing through next to a moved box (F1), the plan-mode in-box chip
(F2), and grip moves on `/Rotate` pages (ROT). Round 1 of the adversarial review (plan section 14, "Round 1
adversarial review") then found and fixed four defects in the F1/ROT work (REG-1, CS1, B1, RPU-2; items below).
Still open or owed:

- [x] **M9-1: encrypted + signed PDF - Save As, or Ctrl+S after an undo, wrote an unreadable file and blanked the live session (round 9).**
  Fixed: `signed_append_save._replayable` read `needs_pass` on the authenticated live handle (PyMuPDF 1.27 then overwrites its crypt key);
  it now reads flags only on the fresh base copy and compares the trailer `/Encrypt` entry. Same class fixed in
  `pdf_optimizer.resolve_file_backed_optimize_source` / `_capture_encryption_descriptor`; AST guard over every `needs_pass` read
  in `model/` + `controller/`. PITFALLS: "Reading `needs_pass` on an authenticated handle blanks it".
- [x] **H10-1: owner-only encrypted signed PDF - Save As / post-undo Ctrl+S fully rewrote the file and dropped the signature (round 10).**
  Fixed: `signed_append_save._same_record` ignores a stream's derived `/Length` when the raw bytes are equal (live plaintext length vs
  appended ciphertext length). AES-256/AES-128/RC4. PITFALLS: "A stream's `/Length` differs between the live handle and the appended encrypted file".
- [x] **H10-2: a 28 KB PDF declaring a 4M-slot xref stream stalled every signed-append save ~70 s (round 10; Part A round 11).**
  Fixed: the replay and the verification compare only the slots MuPDF holds an object for on either side
  (`signed_append_save._in_use_xrefs`, `ll_pdf_object_exists`, same result as the full walk), so the signed append runs on such
  files (4M: 2.6 s, signed prefix kept) instead of round 10's decline, which lost the signature. The unbacked-table guard
  (`MAX_UNBACKED_XREF_SLOTS`, `XREF_SLOTS_PER_SOURCE_BYTE`) is only the fallback without the census primitive (LS-3 and the
  open-time read still use it); `MAX_APPEND_GROWTH_SLOTS` bounds the pad loop. PITFALLS: "A 28 KB PDF declaring a 4M-slot xref
  stream stalled every signed-append save".
- [x] **F10-FS-2: Save As to a name with a trailing dot/space left the session under a dead key (duplicate tab on reopen) (round 10).** Fixed: `_canonicalize_path` mirrors the Win32 name stripping for paths that do not exist yet and `save_as` re-derives the key after the write. See PITFALLS. The "both tabs write" claim was not reproduced (the already-open guard fires).
- [x] **F10-FS-3: Save As that only changes the name's case (a.pdf -> A.pdf) renamed the tab but not the file (round 10).** Fixed: install targets keep the typed spelling (`utils/path_staging.resolve_as_requested`), case-only rename skips the incremental path. See PITFALLS.
- [x] **F11-FS-3: plain Ctrl+S reverted an external case-only rename (`report.pdf` -> `Report.pdf`) of a memory-backed session (round 11).** Fixed: `save_as` treats a name equal to the stored one (same file) as a replay and installs under the on-disk spelling (`utils/path_staging.on_disk_spelling`). Residual (accepted): the stored name typed in Save As over an externally re-cased file is indistinguishable from Ctrl+S and keeps the on-disk case. See PITFALLS.
- [x] **F11-OPEN-1: detaching an encrypted tab gave the new window a decrypted document; Ctrl+S there wrote the file back without its password/permissions (round 11).** Fixed: the transfer snapshot keeps the encryption (`capture_session_transfer_bytes`, `encryption=KEEP`) and `import_session_transfer` re-authenticates with the payload password, refusing a locked snapshot. See PITFALLS.
- [x] **F11-OPEN-2: detaching a tab re-measured the on-disk fingerprint, so a foreign rewrite the original window refuses to overwrite was silently overwritten from the new window (round 11).** Fixed: `SessionTransferPayload` carries the sender's `disk_fingerprint` / `disk_fingerprint_path` and `import_session_transfer` installs them unchanged (never re-measures); a payload without one gets no baseline. See PITFALLS.
- [x] **F11-ANN-1: a rebuild, push-down or textbox move duplicated every overlapping non-FreeText annotation and left infinite-rect Highlight/Underline markers without QuadPoints, persisted on save (round 11).** Fixed: `_restore_annots` re-creates only what `apply_redactions` actually removed (checked by xref after the redaction), moves survivors in place for the push-down (`offset`, `_translate_annot`), rebuilds text markup from quads and deletes a half-inserted marker; StrikeOut/Squiggly codes corrected. See PITFALLS. Links: fixed by F11-ANN-3. Still open: the FreeText re-create is lossy (F11-ANN-5).
- [x] **F11-ANN-2: after a rebuild + undo on a page with a Highlight and a FreeText, the annotation list of the still-loaded page was stale; later edits on that page, the annotation panel and the visibility toggle raised "xref N is not an annot of this page" until reopen (round 11).** Fixed at the chokepoint: `restore_page_graph` resyncs MuPDF's loaded pages (`utils.pymupdf_refs.sync_open_pages` -> `pdf_sync_open_pages`) after any write. See PITFALLS.
- [x] **F11-ANN-3: a rebuild, same-page drag, textbox move or push-down silently deleted the URI/GoTo links over the redacted rect; redo and Save As kept the loss (round 11).** Fixed: `_save_overlapping_annots` also saves links (`page.annots()` never lists them), and `_restore_annots` moves the original link object by its offset, appends it back to `/Annots` and resyncs the loaded pages. See PITFALLS. Open (owner): a link under a dragged line stays at its old rect, like every other annotation (F11-ANN-1 placement), and does not follow the text.
- [x] **F11-ANN-4: FreeText (and form-field) appearance text was indexed as an editable page block, so a consented rebuild or push-down next to it replayed it into the content stream (it showed twice and survived the annotation's deletion) and a consented rebuild of the "block" painted the new text into the content while the annotation kept the old (round 11).** Fixed: the index, the index-aligned lookups, the protected-span capture / validation, the glyph-survivor check and the push-down extract through `model/page_content_text.content_text` (display list without annotations). See PITFALLS. Open (owner, by design): `text_commit.verify` and search still read annotation text as visible text; editing an annotation's body stays with the annotation tools (legacy FreeText read-only); a FreeText/form body is no longer a click target of the inline text editor; a bare annotation inside a push-down overflow zone no longer travels with the pushed text (it used to, together with burned-in copies of its text) -- owner: should it?
- [x] **F11-ANN-5: a consented rebuild, push-down or textbox move over a FreeText replaced it with a re-created one: text colour = the old /C background, fixed 10.5 pt, yellow fill, /Rotate = page rotation on rotated pages, no author / dates / /RC / /IT, new xref (round 11).** Fixed: `apply_redactions` only unlists a FreeText (object and appearance stay), so `_restore_annots` now moves and relists the same object like a link (`_reattach_entry` / `_reattach_annot`, generic over subtype); only an entry whose object is gone is re-created, from the `/DA` / `/C` / `/Rotate` saved with it. See PITFALLS. Not done: the re-create fallback does not carry `/RC` or `/IT` (no known path reaches it with a live document).
- [x] **F11-ANN-6: the toolbar annotation show/hide toggle (`AnnotationTool.toggle_annotations_visibility`) raised AttributeError on any document with a Text/FreeText annotation: `fitz.ANNOT_FLAG_HIDDEN` does not exist in PyMuPDF 1.27 (round 11; present at HEAD).** Fixed: uses `fitz.PDF_ANNOT_IS_HIDDEN`; `test_every_fitz_attribute_used_in_source_exists` guards the bug class. See PITFALLS.
- [x] **F11-OPEN-3: the password-retry check matched "encrypted" / "需要密碼" anywhere in the model's error text, which embeds the user's path, so a corrupt or missing file under `...\Unencrypted Exports\` looped on password prompts and the real error was never shown (round 11).** Fixed: typed `PdfPasswordRequiredError` / `PdfPasswordRejectedError` (`PdfPasswordError(RuntimeError)`) raised by `PDFModel.open_pdf` and `_guard_foreign_doc`; the controller's `open_pdf` loop and `_open_source_with_password_prompt` (shared by `_resolve_merge_file` and `resolve_insert_source_file`) catch the base `PdfPasswordError` and never read message text. See PITFALLS.
- [x] **F11-1: a second launch / file-association hand-off that arrived while a modal dialog was open switched the active tab under it, so Save As wrote the newly opened document's bytes under the name the user picked for the old one (and renamed that tab), merge-into-current appended to the new tab and the optimized copy held the new tab's content (round 11).** Fixed at the chokepoint: `handle_forwarded_cli` and the optimize worker's success handler (the other activation from outside the user's flow) go through `PDFController._run_when_session_activation_allowed`, which waits until no modal / popup is up (the background jobs' own `show()`-n progress dialogs excepted), keeps arrival order and never drops a hand-off. Defence in depth for the controller-owned dialogs: merge-into-current refuses if the active tab changed under its dialog, and the optimize submission is bound to the tab its dialog was opened for. See PITFALLS. Open: (1) the native Windows file dialog was not driven (offscreen tests use a real `QDialog.exec()`; Qt registers a native dialog's `QFileDialog` as modal, by source reading); (2) the View-hosted dialogs (Save As, metadata, export pages, insert/watermark/OCR dialogs) still read the active session after `exec()` and rely on the gate alone -- pinning them needs the session id carried through the View signals; (3) owner: the deferred hand-off opens once the dialog closes; the alternative (open as a background tab without activating) was not chosen.
- [x] **F11-2: a second launch / file-association hand-off while the running instance's GUI thread was busy for more than 2 s (save joining the thumbnail worker then writing, or the startup `open_pdf` loop) was silently lost: the sender's 2 s timeout covered the payload write wait (on Windows it does not finish until the primary reads), then `socket.abort()` dropped the hand-off and `main.run` returned 1 with no dialog (round 11).** Fixed in `utils/single_instance.py`: `CONNECT_TIMEOUT_MS` (2 s, alive vs dead) is separate from `RESPONSE_TIMEOUT_MS` (60 s, one deadline for write + ack, warning logged on expiry). Tests: real subprocess busy-primary test in `test_single_instance_forwarding.py` (red-first). See PITFALLS. Open: (1) owner: a hand-off that still fails (primary hung beyond 60 s, or no live server) exits 1 with no user-visible message; a dialog or fallback window was not chosen; (2) only the Windows named-pipe path was exercised; (3) the busy GUI thread itself (synchronous save / startup open) is untouched.
- [x] **F11-3: a hand-off the running instance rejects (any token missing, a directory, or without a `.pdf` suffix) used to drop the valid files too and exit 1 with no UI (round 11, owner decision B).** `utils/single_instance.py` now has one shared per-token predicate `forwarded_token_is_acceptable` (the receiver's whole-message fail-closed filter is `all(...)` over it, unchanged in effect) and `partition_forwardable_argv`; `main._hand_off_to_running_instance` forwards the valid tokens as one message and shows a Traditional Chinese dialog naming the rejected ones (nothing forwarded when none is valid). Tests in `test_scripts/test_single_instance_forwarding.py`. Open: extension-less real PDFs are still rejected (option C not chosen); a transport-level failure (primary hung over 60 s, no live server) still exits 1 silently (F11-2 open item 1); not driven through a real second OS-level launch with the modal box.
- [x] **H10-3: a /Prev loop made MuPDF read 0 pages, the editor substituted a blank page and Ctrl+S overwrote the signed file (round 10).**
  Fixed: `open_pdf` refuses a 0-page file (RuntimeError, no session, file untouched) and `_guard_foreign_doc` rejects 0-page merge/insert
  sources. PITFALLS: "A file MuPDF reads as 0 pages was replaced by a blank page". Residual (owner/UX): no read-only/repair-copy open for such files.
- [x] **LS-3: every edit -> undo -> save cycle left free xref slots in the file, growing it across sessions without bound (round 8; owner option B, round 10).**
  Fixed: `open_pdf` compacts the IN-MEMORY document (`model/xref_compaction.py`: the bytes of `tobytes(garbage=2)`, written by
  `doc_bytes.serialize_doc` into MuPDF's native in-memory sink, then `fitz.open`) when the file's free
  slots are >= 512 and >= 50 % of the table (size cap 64 MB, census cap 200,000 slots); signed and encrypted files are skipped. The file on disk
  stays byte-identical until the next real save and the session is not dirty. Accepted: growth WITHIN a session (the numbering rule keeps
  `garbage=1` saves), a file opened and never saved keeps its slots, and a compacted session is memory-backed (incremental saves off until
  the next open). PITFALLS: "A plain edit -> undo -> save session leaves free xref slots that are never reclaimed".
- [x] **H10-2 residual: every full serialization of such a file took ~19 s (round 10; Part B round 11).** The round-10 diagnosis
  "MuPDF's own writer is O(declared slots)" was wrong: MuPDF writes the 80 MB in 0.35 s; the 18.6 s was PyMuPDF's Python
  file-object sink behind `tobytes()` / `save(io.BytesIO)`. Fixed: every snapshot goes through `model/doc_bytes.serialize_doc`
  (temp file, or an in-memory MuPDF buffer for decrypted copies of encrypted documents, caller-flagged plaintext copies and
  secure-latched sessions); 4M snapshot 20.9 s -> 0.41 s, model scenario highlight/undo/highlight/save/highlight/save 148 s -> 9.1 s. Round 12 (F12-H102-1): the text-commit engine and preview session had bypassed the secure-latch rule (temp files in the system temp root); they now take the model's funnel as an injected `serialize` callable, PITFALLS.
  Round 12 (F12-H102-2): a failing temp file (dir removed, volume full) falls back to the in-memory sink inside `serialize_doc`, so no edit depends on a writable disk.
  Options considered: ~~(c) snapshot with `use_objstms=1`~~ -- struck: `tobytes(use_objstms=1)` mutates the live handle (two
  container objects per call, doc left dirty) and a state reopened from such bytes declines the signed append; (a) / (b) moot.
  Not switched: the open-time repair round trip (`tobytes(garbage=1)`, bounded). Snapshot memory is still O(declared
  slots). PITFALLS: "Every whole-document snapshot took ~19 s on a 4M-slot table".
- [x] **SIG-DIALOG: a signed save that could not append silently fell back to a full rewrite and invalidated the signature (owner decision, round 10; implemented round 11).** The model raises `SignatureWouldBreakError(reason_code, path)` before writing and only rewrites with `allow_signature_loss=True` (`save_as`, `save_session_as`); the controller asks on Ctrl+S, Save As, close-with-save and Save All (zh-TW dialog: save anyway / cancel, suggests Save As) and retries on consent; a cancel writes nothing and keeps the tab dirty; the dialog names the signed document and, when it is not the active tab (Save All / per-tab close), tells the user to switch to that tab before Save As (F12-DLG-1, round 12). Covers the secure latch, incremental saving off, a repaired/spent file-backed handle, a changed or vanished source, encryption mismatch, catalog mismatch, the growth cap, failed verification, a replay error, the watermark clone and a failed in-place append (a half-written append is rolled back and the fingerprint re-recorded so the consented retry is not refused as a foreign change, F12-SIG-1 round 12). Open: not driven through the real GUI with a human; no real PKCS#7 validator run. PITFALLS: "A signed save that could not append silently fell back to a full rewrite".
- [x] **H10-2 Part C (owner decision, round 10: ACCEPT, documented):** on a file declaring far more slots than it has bytes, new
  objects get numbers above `file_size / 3`, which qpdf 12 / pikepdf ignore (the new annotations read as `null` there; MuPDF,
  pypdf and poppler show them; the native incremental Ctrl+S always had the same limit). Relocating new objects into low free
  slots was not taken. PITFALLS: H10-2 entry, Residual.
- [x] **F1: after a grip move of an existing text the original glyph stayed visible at the old spot** (manual
  step S17a, copy of `ecc-dwg.pdf`: "備備為C標新設。"). Fixed: a second item `_text_editor_origin_mask_item`
  (z 10.5, untinted ring mean of the origin page, source span plus a 1 pt margin) covers the open spot while an
  `edit_existing` box is displaced. After the round 1 review the cover is the SOURCE SPAN (not the editor widget)
  plus the margin, snapped outward, and it is skipped on a non-uniform ring (items below). Guards: `test_grip_move_hides_the_source_text_at_its_old_spot[0|90|180|270]`,
  `test_grip_move_leaves_no_source_glyph_or_sliver_on_the_owner_run[100%|214%]` (ecc copy, needs fixtures) and the
  lifecycle tests in `test_text_commit_editor_mouse_gestures.py`.
- [x] **REG-1: the origin patch covered the editor widget, not the source span.** A short run next to another run
  on the same baseline lost the neighbour's ink at the old spot (115 dark pixels -> 0; patch 82 x 16 px against an
  18.7 px span). Fixed: `_editing_origin_span_scene_rect` (visual-page space) is the cover, ring sample and
  signature source; the widget rect only drives the displacement test. Guard:
  `test_origin_patch_covers_the_source_span_not_the_editor_widget[0|90|180|270]`.
- [x] **CS1: a keep-finalize (save, rescale) during a grip drag killed the drag**, so `editing_rect` stayed at
  the original while the box and patch showed the new spot. Fixed: `finalize_text_edit_impl` completes the drag
  first. Guard: `test_a_keep_finalize_mid_grip_drag_completes_the_drag[...]` (8 ids). Residual: a non-grip body
  drag would also go through `_on_move_grip_finished` (not exercised; the grip is the only mover).
- [x] **SCN-1: the search-jump highlight was hidden under the origin patch.** The red search-hit rect was added at
  z 0, under the patch (z 10.5), so a jump to the run's old spot while its box was moved showed blank page. Fixed:
  the rect is `_SEARCH_HIGHLIGHT_Z` = 10.75 (above the patch, below the moving mask 11). Guard:
  `test_search_jump_highlight_is_drawn_above_the_origin_patch_while_the_box_is_moved`.
- [x] **SEQ-1: the grip's own press latch survived a finalize whose release was swallowed** (modal dialog from
  Ctrl+Shift+S etc.), so the next grip drag did nothing. Fixed: `EditorMoveGrip.reset_drag()` + `hideEvent`, called
  from `_on_move_grip_finished` and the finalize drag-state reset; a press on a latched grip restarts the drag.
  Guards: `test_a_finalize_that_swallows_the_grip_release_leaves_the_next_grip_drag_working[...]` and two more.
  Not driven: the real native dialog.
- [x] **SEQ-2: a grip drag left live by a swallowed release was dropped by an in-box click without finishing (commit at
  the old spot), or glued the box to the hovering pointer.** Fixed: `_settle_lost_grip_drag` at the top of
  `_mouse_press` and in the button-less ACTIVE `_mouse_move`; a new grip press finishes the stale drag first. Guards:
  `test_an_in_box_click_after_a_lost_grip_release_...`, `test_a_button_less_move_after_a_lost_grip_release_...`,
  `test_a_second_grip_press_after_a_lost_release_...` (x4 rotations). Not driven: the real native dialog.
- [x] **MT-2: Ctrl+W / Alt+F4 while the grip button is still held skipped the unsaved prompt and dropped the box move.**
  Fixed: `TextEditManager.has_unapplied_input` (the one source of the close question) first calls
  `_settle_lost_grip_drag`, so `editing_rect` follows the displaced box before it is compared. Guards:
  `test_mt2_ctrl_w_during_a_held_grip_drag_asks_and_cancel_keeps_the_move`, `test_mt2_app_close_during_a_held_grip_drag_asks`,
  `test_mt2_a_held_grip_press_that_never_moved_is_not_unapplied_input`. Not driven: a real OS key event with the mouse held.
- [x] **R7-DEG-1: a span whose own bbox crosses the page edge jumped on the first grip nudge and could not return to
  its open spot** (font-metric bbox, never clipped to the page; baseline 5 pt from the top gives y0 -5.95). Fixed:
  `_clamp_editor_pos_to_page` allows the page UNION the open proxy spot (`_editing_open_proxy_pos`). Guards:
  `test_a_horizontal_first_grip_move_of_a_span_crossing_the_page_top_never_jumps_y[rot0|rot180]`, the out-and-back
  twin, and `test_dragging_a_page_top_crossing_span_up_stops_at_its_open_spot_...`. Residual EDGE-REFUSE-1 (a zero-growth
  shrink on such a span was refused `growth_outside_page` at plan stage) fixed: `_build_tier1` runs `_bbox_within_page`
  only for real growth (guards in `test_text_commit_tier1_slice1.py`); the bottom
  edge / 90 / 270 variants were not reproduced.
- [x] **E2E3-1: moving a line under 5 pt tall on a /Rotate 90/270 page was silently dropped by the legacy rebuild apply
  (text snapped back to its old spot, log warning only).** Fixed: the `new_rect` sliver guard compares against the
  requested width, not a flat 5 pt on the unrotated rect (`model/pdf_text_edit.py`). Guard:
  `test_legacy_move_of_a_short_line_lands_at_the_dropped_place[270-...]`.
- [x] **E2E3-1 residual (ROT90-UP-1): a legacy rebuild of upward-reading text (`dir (0,-1)`, /Rotate 90 drawing
  layout) landed at the unrotated page bottom, moved or not (and, with no `new_rect`, 8.5 pt off its line).**
  Fixed (round 7, round 4): the vertical branch of `_apply_redact_insert_body` pins the rect on the htmlbox's text
  start (upward text starts at the BOTTOM edge and its first line sits at the LEFT edge, so the rect now runs from the
  page top down to the run's bottom, left edge fixed; `_binary_shrink_height(grow_up=True)` mirrors the shrink), and
  the line height of a quarter-turn run comes from the bbox WIDTH / origin.x advances, not the bbox height (= text
  length, which scaled a tight `new_rect` run to 43 % and pushed the no-rect run 8.5 pt inward; /Rotate 270 too).
  Guards: `test_legacy_rebuild_of_quarter_turn_drawing_text_keeps_its_place[90|270 x unmoved_rect|no_rect]` and
  `test_legacy_move_of_a_short_line_lands_at_the_dropped_place[90-...]`. Still not reproduced on a real fixture (no
  local /Rotate 90 page with upward text). Residual: `vertical_shift_left=False` on DOWNWARD text still anchors the
  left edge although its first line is at the right edge (no caller passes False).
- [x] **F13-VF-4: the legacy rebuild re-drew the edited word wider at its old origin and overprinted the next run on the
  line (`01_報告書.pdf` p3 `SCORE` -> `CSORE` ran over the subscript `EE` and touched `=`).** Fixed (round 13):
  `_right_neighbour_limit` bounds the fast path, the htmlbox rect and strategy B by the next untouched run on the line;
  a word that does not fit is wrapped, shrunk (down to 50 %) or refused (`TEXT_DOES_NOT_FIT`), the page-edge policy.
  Owner option, not taken: refuse instead of shrinking. Guards: `test_rebuild_*neighbour*` in `test_edit_text_helpers.py`.
- [x] **F14-VF4-OVERLAP (round 14): the F13-VF-4 neighbour wall skipped a right-hand run that starts 0.25 pt or more
  inside the edited extent, so the grown edit still overprinted it (SUCCESS).** Fixed: such a run (past the edit's origin,
  sticking out of the extent's right edge) is a wall at the extent's old right edge; the edit shrinks, wraps or is refused.
  See PITFALLS F13-VF-4 (Round 14 paragraph). Only an axis-aligned run (0/90/180/270 degrees) counts as a neighbour;
  a diagonal run's bbox is not its footprint (F15-VF4OV-DIAGONAL, below).
- [x] **F15-VF4OV-DIAGONAL (round 15): the neighbour wall, the wrap floor and the overprint guard treated the bbox of a
  diagonal text watermark (45 degrees, 60 pt) as text on the edited line, so an edit was refused or shrunk.** Fixed:
  `_is_axis_aligned_dir` gates `_right_neighbour_limit` and `_wrap_floor`; off-axis glyphs get their own turned ink core
  (`advance` in `_PageGlyph`, separating-axis overlap). See PITFALLS F15-VF4OV-DIAGONAL.
  Settled by the owner after round 15: edited text may print over off-axis runs (D-DIAG-INK, below).
- [x] **D-DIAG-INK (round 16, owner decision): the overprint guard refused edits that printed over a diagonal
  watermark's ink.** Fixed: `_new_text_overprints` ignores untouched glyphs written off the page axes; horizontal and
  vertical runs still block. The watermark stays intact (tests compare glyphs, directions, origins and pixels). See
  PITFALLS D-DIAG-INK. The watermark glyph under the OLD word's box was settled afterwards (S17-WMARK-UNDER, below).
- [x] **S17-WMARK-UNDER (round 17, owner decision 2026-10-12): editing a word whose OLD box lies on a diagonal watermark
  erased watermark glyphs with it and the edit was refused `UNTOUCHED_TEXT_WOULD_BE_LOST`.** Fixed: off-axis runs are no
  overlap-cluster member of an upright edit, and `_redact_owned_glyphs` puts back the turned shows the redaction erased by
  their glyph box (`model/off_axis_shows.py`, exact original operator bytes, original drawing order). Horizontal and
  vertical untouched text keep today's protection. See PITFALLS S17-WMARK-UNDER.
- [ ] **S17-WMARK-UNDER follow-up (open):** a turned run inside a Form XObject (Acrobat-style watermark) is still erased by
  the redaction and the edit still refused; the repair reads the page's own content streams only. Needs the form's
  invocation matrix to tell turned text, plus a stream-by-stream pairing for forms. Not checked in the real GUI.
- [x] **F14-VF4-WRAP (round 14): a growing edit wrapped (at the F13-VF-4 neighbour cap, or at the page margin) and the
  wrapped lines were drawn over the next lines of the same paragraph, reported SUCCESS.** The push-down moves only blocks
  that start below the edit. Fixed: `_wrap_floor` bounds the htmlbox at the next untouched line the push-down will not
  move (same rule, `_push_down_can_move`), with no wrap when only one line fits; the pre-push probe runs the A/B/C chain;
  `_new_text_overprints` rolls back any in-place horizontal insert drawn over untouched text (`TEXT_DOES_NOT_FIT`).
  Effect: lengthening a mid-paragraph word now shrinks it on its line or is refused (corpus `better-than-ever`).
  See PITFALLS F14-VF4-WRAP.
- [x] **F14-DT-1 (round 14): the legacy / consented rebuild clamped the edited word's htmlbox to the page's safe right
  margin even when the word already reached past it, so a title or page number in the margin was re-wrapped, pushed the
  lines below down, or was refused (`TEXT_DOES_NOT_FIT`) where Tier 0/1 commit it in place.** Fixed: `_right_wall` (shared
  by the fast path's `fast_available_w`, the htmlbox rect and its `max_w`) is the safe margin only for text that ends
  inside it; text already past it is walled at page edge - 10 pt (single line) or its own old right edge (paragraph).
  Corpus `ecc-dwg.pdf` p1 `平面配置圖` -> `機房配置圖` now stays one line in place. Still wraps (5+1, nothing pushed) when the
  new text is wider than the room left on the page. See PITFALLS F14-DT-1.
- [x] **F14-VM-2 / F14-MM-3 (round 14): the consented rebuild drew the edited text by its htmlbox rect corner, so every
  in-place edit sat +1.0 pt right and a substitute-font baseline off (+2.49 pt at 48 pt) and each same-page drag added the
  same error, so a drag and its inverse never returned the text.** Fixed: `_align_htmlbox_rect` measures the first glyph on
  a scratch page and moves the rect (same size) so it lands on `_start_glyph_origin` + the drag, for strategies A/B/C and the
  vertical insert, all rotations and `/Rotate` pages. Residual: the cross-page move destination is still a rect-placed
  `add_textbox`; the nominal layout rect (reopen anchor) is unchanged. See PITFALLS F14-VM-2.
- [x] **F15-VM2-RTL (round 15): the F14-VM-2 placement aligned the first DRAWN glyph, so a rebuilt Hebrew word moved
  left by its own width (27 / 51 pt, SUCCESS) and a replacement starting with a blank line was pulled back onto the
  original baseline; a protected Hebrew neighbour moved the same way.** Fixed: one geometric start rule
  (`_start_point`) on both sides (`_start_glyph_origin` / `_drawn_text_start`), leading `<br>`s measured on the markup
  without them, push-down target = the span's geometric start. See PITFALLS F15-VM2-RTL.
- [x] **F15-DEADTAB-APPCLOSE (round 15): window close with Discard all dropped a lost tab without showing its recovery path.**
  Fixed: `_show_lost_discard_notice` is shared by the single-tab and the window-close discard; the prompt names each lost tab's
  copy. The copy still goes at program exit (owner decision C), not at close. See PITFALLS F15-DEADTAB-APPCLOSE.
- [x] **F15-VM2-FAST180 (round 15): the rebuild fast path drew an upside-down (text rotation 180) run upright.** A consented
  rebuild `ab` -> `abc` of a 180-degree run returned SUCCESS with the new glyphs at +x from the old origin (the word grew
  the other way and flipped). Fixed: `_classify_insert_path` sends every turned run (`rotation != 0`) to the htmlbox. Same-class
  sites fixed in the same pass: the protected-neighbour replay passed the index rotation straight to `insert_text` /
  `insert_htmlbox`, so 90/270 neighbours came back reversed; the push-down redrew every pushed span upright (180/270
  blocks flipped; a diagonal block came back horizontal). One mapping `_replay_rotate`; a block with an off-axis line is
  now left where it is (like WMode 1). See PITFALLS F15-VM2-FAST180.
- [x] **F15-G1 (round 15): add_textbox and OCR clamped against raw `page.cropbox`, so their text was lost or shifted on
  pages whose CropBox/MediaBox does not start at (0,0) or whose `/UserUnit` is not 1.** `PDFModel._unrotated_page_rect`
  returned `page.cropbox` (MediaBox-relative, y-flipped, raw PDF units); a CropBox [30 40 500 700] page collapsed a
  top-left textbox to 1x1 (no ink) and an OCR span to a 1x1 word at (30,100), a MediaBox at (50,70) shifted both 40 pt
  right, and at `/UserUnit 2` the bottom-right quarter drew nothing. Fixed: it now delegates to
  `geometry.unrotated_page_rect` (page.rect through `derotation_matrix`, the text-edit path's bound); its two callers
  (`_insert_textbox_visual_content` - add_textbox, textbox move/rotate, the controller's cross-page add - and
  `apply_ocr_spans`) are the only users. See PITFALLS F15-G1.
- [x] **F15-G2 (round 15): image bbox discovery and the image cm writers flipped y against the MediaBox height and
  ignored `/UserUnit`.** On a page whose MediaBox does not start at y 0, or whose `/UserUnit` is not 1, native images were
  discovered off where MuPDF draws them (click missed; a phantom selected 200 pt below), app images could not be moved or
  rotated, and app-image delete removed only the marker while the image stayed drawn. Fixed with one chokepoint,
  `pdf_content_ops.page_user_space_matrix` (`PageVisualFrame.base`, composed in Python floats), used by discovery,
  `fitz_rect_to_stream_cm` and the free-rotation move/resize (this also covers the F15-G3 site); an unprovable page
  frame reports MuPDF's own placement and refuses cm writes. See PITFALLS F15-G2.
- [x] **F15-G4 (round 15): an app textbox on a `/Rotate` page with a non-zero CropBox/MediaBox origin was drawn
  offset from its box; a move then left the old copy drawn (duplicate text).** PyMuPDF's `insert_htmlbox` places through
  `page.transformation_matrix`, which drops the CropBox/MediaBox origin once `/Rotate != 0`. Fixed at the model's one
  htmlbox chokepoint: `insert_htmlbox_tracked` shifts the rect by `transforms.pymupdf_writer_shift(page)`, which also
  fixes the legacy rebuild / push-down / neighbour-replay htmlbox sites (a legacy edit on such a page drew its text
  30-41 pt off). See PITFALLS F15-G4.
- [x] **F15-G5 (round 15): a watermark on a `/Rotate` 90/270 page was off-centre, turned with the page and moved vertically by the horizontal offset.** `apply_watermarks_to_page` fed the displayed-page centre to `insert_text` (which works in the unrotated frame) with an angle-only morph. Fixed in the one renderer shared by the live overlay, the save path and the print helper: the centre and offsets go through `model.geometry.visual_to_unrotated_point` and the morph angle is `angle + page.rotation`; upright pages render pixel-identically to before. Tests `test_watermark_rotated_pages.py` (ink oracle: a rotated page equals the upright page of the displayed size; 90/180/270 x plain/CropBox/negative MediaBox x flat/offset/diagonal/vertical; horizontal text, offsets right/down, save path, mixed document). Owner-visible: a file saved by an older build with a watermark on a `/Rotate` page shows two copies on reopen (the baked ink is at the old wrong place, the restored overlay at the right one). Open: not eyeballed in the GUI; `/UserUnit != 1` (F15-G1-UU); a non-quarter-turn `/Rotate` literal. See PITFALLS F15-G5.
- [x] **F15-G5-GEOM (round 16, owner decision: fix and accept the doubled look): the upright watermark geometry was wrong at every angle other than 0.** `apply_watermarks_to_page` pre-turned each line's origin by `angle` and then let `insert_text(morph=(centre, mat))` turn it again (45 degrees, the dialog default: ink centre about 80 pt off; 90 degrees: about a quarter page) and hung the block half a line above the centre. Fixed in the one shared renderer: the origin is `centre + (dx, dy)` unrotated with `dy = -total/2 + (i + 0.5) * line_height + 0.35 * font_size`, the morph alone turns it; F15-G5 / F15-G6 behaviour kept. Ink-oracle tests in `test_watermark_rotated_pages.py` (angles 0/45/90, single and multi-line, `/Rotate` 0/90/180/270, offsets; overlay, save clone and print helper agree). **Owner-accepted, no migration:** a file saved by an older build (any build before F17-COH-2 marked its baked ink) shows TWO copies of its watermark on reopen (the baked ink at the old place, the restored overlay at the new one); delete and re-add the watermark to get one, the old baked copy stays as page content. Open and unmeasured in the GUI: a CropBox larger than the MediaBox displaces `insert_text` by the unclipped origin at every rotation (measured on MediaBox [0 0 600 800], CropBox [-50 100 400 900]: ink 50 pt left and 100 pt up); not eyeballed in the real app. See PITFALLS F15-G5-GEOM.
- [x] **F15-G4-IMG (round 16, fixed with F14-MM-1b): `add_image_object` now derotates the visual rect, then applies `shift_rect_for_pymupdf_writers`.**
  An app image on a `/Rotate` page with an offset CropBox/MediaBox is drawn at the requested visual rect (ink tests over
  0/90/180/270 x plain/crop/negmb in `test_image_objects_model.py`). See PITFALLS F14-MM-1b.
- [x] **F15-G2-ANNOT (round 16): a link under a redaction was missed, and a moved annotation shifted by the wrong vector, on a `/Rotate` page with an offset CropBox/MediaBox or `/UserUnit`.** `AnnotationTool._save_overlapping_links` and `_translate_annot` used `page.transformation_matrix` (drops the CropBox/MediaBox origin and `/UserUnit` once `/Rotate != 0`), and `_save_overlapping_annots` compared `Annot.rect`, which drops `/UserUnit` on a rotated page (y = -512 for a rect at y 150 on `/Rotate 90` + `/UserUnit 2`). Measured with a rendered-ink box, `PageVisualFrame.base` and a real `apply_redactions` (a link is overlapped exactly when the redaction removes it): links missed on 5 of 7 rotated configs (displaced by the dropped CropBox origin), moves 2x the requested vector at `/Rotate 90/270` + `/UserUnit 2` (and wrong at 180). Fixed by mapping the raw `/Rect` and the move vector through `pdf_content_ops.page_user_space_matrix` (`AnnotationTool._user_to_page_matrix`, `_raw_rect_to_page`, `_annot_page_rect`, `_annot_page_vertices`: a markup's `Annot.vertices` dropped `/UserUnit` the same way), computed once per snapshot, in Python floats; an unprovable frame falls back to MuPDF's own matrix as before. Tests `test_edit_text_helpers.py` (`..._on_rotated_offset_pages`, `test_a_square_under_a_redaction_is_saved_with_its_page_space_rect`, `test_a_highlight_under_a_redaction_is_saved_with_page_space_vertices`, `test_translate_annot_moves_the_rendered_ink_by_the_requested_page_vector`; 0/90/180/270 x UserUnit 1/2 x plain/CropBox/negative MediaBox). See PITFALLS F15-G2-ANNOT. Open, not measured: the other `Annot.rect` consumers on a rotated `/UserUnit != 1` page (`pdf_object_ops._app_object_true_rect` and the marker/hit paths, the re-create in `_restore_annot_entries`, which hands page-space rects/quads to `add_*_annot`, `AnnotationTool._pin_outer_rect`, the Text/FreeText listing `_rotate_rect_to_displayed`, `add_*_annot` via `derotation_matrix`) belong to TODOS F15-G1-UU.
- [x] **F15-1 (round 15): an object selection survived page delete / insert / reorder / rotate, a tab switch and undo,
  so Delete removed a native image on a DIFFERENT page** (positional `native_image:<page>:<occurrence>` ids; an app object
  became a silent no-op). Fixed: both View scene-clear sites drop the object selection with the text selection, and
  `PDFController.undo`/`redo` drop it after a successful step (`_drop_object_selection`, also used by `add_image_object`).
  Behaviour change: a zoom also drops the selection (its overlay was already destroyed by the rebuild). Tests in
  `test_object_manipulation_gui.py`. See PITFALLS F15-1.
- [x] **F15-5 (round 15): undo/redo of an object move left the frame and 8 handles at the old position and a handle drag
  relocated the object there.** Same cause and fix as F15-1 (`_drop_object_selection` in undo/redo); pinned by a real-mouse
  test (rect/image x undo/redo) in `test_object_manipulation_gui.py`. See PITFALLS F15-1.
- [x] **F15-6 (round 15): Rotate Object to 90/270 on an app textbox re-flowed the text into the unturned box and shrank it
  to about half size.** `rotate_object` now turns the box with the text (width and height swap about the centre on a quarter
  turn, slid inside the page), so font size and lines are unchanged and the hit bbox/frame follow the visible text.
  Behaviour change: the textbox rect is no longer the pre-rotation rect after a quarter turn. A turned box larger than the
  page is still cropped and may shrink. Tests in `test_object_manipulation_model.py`. See PITFALLS F15-6.
- [x] **F15-2 (round 15): Rotate / Move Object on a textbox whose words had been edited put the OLD words back**
  (the marker payload was written once at `add_textbox`; also after save/reopen). Fixed: `edit_text` syncs the marker
  text on both success exits (`pdf_object_ops.sync_textbox_markers_after_text_edit`; emptied or dragged-out box drops
  the marker, ambiguous edit (words twice in the box) flags it `content_unsynced`, a longer text grows the box over the new words) and move/rotate refuse a textbox whose stored text the page
  no longer draws in its rect (`_textbox_payload_drawn_on_page`). Tests in `test_object_manipulation_model.py`. See PITFALLS F15-2.
- [ ] **F15-2 follow-ups (open: (c) only):** (a) DONE round 16 decisions pass (D-OLD-MARKERS, owner: repair + message): a
  stale-marker textbox is re-resolved from its one htmlbox drawing (same centre, same angle, all the box holds, text
  verified against htmlbox's own layer); otherwise move/rotate/delete refuse with one zh-TW message. (b) DONE round 16 (F13-VF-2b): a grown box that covers page text
  between the old rect and the new words now refuses move/rotate/delete instead of erasing it (with the message since D-OLD-MARKERS). (c) A partial restyle (one line of a multi-line box) is
  not representable in the one-style payload: a later move/rotate redraws the whole box in the stored style.
- [x] **F16-1 (round 16): Move / Rotate / Delete Object refused every app textbox with emoji, Devanagari, Arabic or CJK Ext-B,
  even right after `add_textbox`.** The object ops compared the raw stored text with htmlbox's lossy text layer (guard,
  form identity, fallback foreign-text check). Fixed: they compare with the text layer htmlbox writes for the stored text
  (`pdf_object_ops._textbox_layer`, scratch render of the shared `_textbox_markup`; glyph ids for an Ext-B-only box). Tests in
  `test_object_manipulation_model.py`. See PITFALLS F16-1.
- [x] **F16-1-LOSSY (round 17): a text edit of a lossy textbox left its marker stale, so the next Move/Rotate refused,
  and a longer text did not grow the box.** The sync matched the index text of the edited run (htmlbox's lossy layer:
  U+1F600 reads back as U+1F60) against the RAW stored text, found nothing and skipped the marker. Fixed: when the raw text
  does not hold the edited text, `sync_textbox_markers_after_text_edit` looks for it in the text layer htmlbox writes for
  the stored text (`_textbox_reference_text`), aligns the two (`_lossy_span_ignoring_whitespace`) and replaces the raw
  characters it maps to; an ambiguous or unalignable source flags the marker `content_unsynced` (refuse, never guess).
  The growth step reads the new text through the same layer and grows over a word that only STRADDLES the box edge
  (`_grow_box_over_new_words` used the word's centre, so a long line's last word stayed outside for Latin text too).
  Tests `test_f17_*` in `test_object_manipulation_model.py`. See PITFALLS F16-1-LOSSY.
- [ ] **F16-1 follow-up (open):** the guard cannot tell apart two characters htmlbox writes as the same code point; an
  Ext-B-only box over foreign page text is refused (no form identity without comparable characters); a lossy edit source
  the alignment cannot pin down (two emoji in one box, a span ending inside a lossy stretch) flags the marker and the
  next move/rotate refuses; editing the emoji run itself (font `NotoEmoji`, the htmlbox subset) raises `TextEditRefused`
  ("need font file or buffer") before any commit, so nothing changes (font resolution of the embedded emoji font; not in
  the marker sync).
- [x] **D-OLD-MARKERS (round 16 decisions pass; owner decision after round 15: repair + message): object ops on old
  or unresolvable markers failed silently and Delete could remove only the hidden marker.** Fixed: unique-candidate
  repair for image markers (digest, angle, centre) and textbox markers (one same-centre, same-angle htmlbox form that is
  all the box holds); every refused Move/Resize/Rotate/Delete records an `ObjectOpRefusal` code
  (`PDFModel.last_object_op_refusal`) and the Controller shows one zh-TW sentence (`controller/object_op_refusals.py`),
  with a count for a batch; Delete removes both or refuses. Tests in `test_image_objects_model.py`,
  `test_object_manipulation_model.py`, `test_object_controller_flow.py`. See PITFALLS D-OLD-MARKERS.
- [x] **F16-2 (round 16): an upside-down (text rotation 180) rebuild was walled at the run to its +x side and unwalled toward
  -x.** After F15-VM2-FAST180 routed every 180 run to the htmlbox, 'Hello World' written upside down edited 'World' ->
  'Worldwide wonders' at 8 pt on two lines and rolled 'Hello' -> 'Hello there' back (the upright twin: 14 pt). Fixed: the
  horizontal htmlbox branch is direction aware (`grows_left`): `_horizontal_neighbour_limit(grows_left=)`, `_left_wall`
  (`_right_wall` mirrored), `_wrap_ceiling` (the nearest untouched line above), strategy B toward -x, no pre-push, layout rect
  measured from the bottom. Tests in `test_edit_text_helpers.py`. See PITFALLS F16-2. Open: the preview renderer's box for
  turned text was not re-derived; a dragged upside-down box is uncapped (as upright).
- [x] **F16-NAV-1 (round 16, merged F16-NAV-2): page insert/delete/move/import and every bookmark-panel edit regenerated
  the outline from `get_toc()` simple rows.** Every bookmark lost its /XYZ target, colour, bold and collapse state, URI
  bookmarks became 'go to page 1', and a panel edit raised `ValueError` on any outline with a URI bookmark. Fixed: one
  in-place outline writer, `model/outline_ops.py`: structural ops retarget only the items whose page was deleted
  (`_follow_outline`, colour restored), `straighten_page` moves its bookmarks to the replacement page, and the panel
  carries an outline-item key (`get_toc_rows` -> view -> `set_toc`) so a rename/re-page/reorder edits those objects only;
  `update_toc` catches a rejected edit and reloads the tree. Tests in `test_bookmarks_toc.py`. See PITFALLS F16-NAV-1.
- [ ] **F16-NAV-1 follow-ups (open):** (a) closed by F16-NAV-1a below. (b) A retargeted bookmark gets a whole-page
  `/Fit` view; a page-top `/XYZ` needs a rotation/CropBox/UserUnit-correct corner. (c) The panel shows -1 as the page of
  a URI bookmark and cannot open its link. (d) An outline whose two PyMuPDF walks disagree is rebuilt on a panel edit.
- [x] **F16-NAV-1a (round 17): named destinations, the links and bookmarks using them, and `/OpenAction` dangled after their
  page was deleted or straightened, and kept the deleted page object (with its content) in the saved file.** Fixed:
  `model/page_refs.py` `repoint_page_references` drops (delete) or repoints (straighten) every such reference; the
  decision follows PyMuPDF's own removal of explicit links and `NavigationGraft`'s dropped names. Tests in
  `test_bookmarks_toc.py`. See PITFALLS F16-NAV-1a.
- [ ] **F16-NAV-1a follow-ups (open):** (1) the structure tree (`/StructTreeRoot` `/Pg`), `/Threads` beads and page `/AA`
  still reference a deleted page and keep its object and content in the saved file (tagged PDFs; needs a struct-tree
  prune). (2) An inline `/Names /Dests` tree is left alone. (3) The owner may prefer retargeting a dead name to the
  nearest surviving page (like bookmarks) over dropping it and its links.
- [x] **F16-NAV-3 (round 16): merge (into current, save as new, CLI) and page export dropped the outline, page labels,
  `/Names /Dests` tree and every link PyMuPDF reports as `LINK_NAMED` (named destinations AND explicit `/Fit` /
  `/FitH` / `/XYZ null null 0` ones), for every source including the current document; page import lost the same
  links.** Fixed: `model/navigation_graft.py` `NavigationGraft` copies the pages and carries bookmarks (raw item objects
  through `outline_ops.append_items`, view/colour/flags/collapse/URI kept), links (re-created from the raw rect and
  destination, also a GoTo across insert runs), named destinations (one sorted leaf; a clash is renamed `name.2`, links
  follow) and page labels (a source without labels counts 1, 2, 3 again; prefixes escaped). Used by
  `compose_merged_document`, `export_pages`, `headless_merge`; `insert_pages_from_file` uses it too (S17-INSERT-NAV below). Tests in
  `test_merge_composition.py`, `test_headless_merge.py`, `test_navigation_graft.py`, `test_bookmarks_toc.py`,
  `test_pdf_merge_workflow.py`. See PITFALLS F16-NAV-3.
- [ ] **F16-NAV-3 follow-ups (open):** (a) Insert pages from file: done in round 17 (S17-INSERT-NAV below). (b) A bookmark with a
  GoToR / Launch / JavaScript action keeps its title but loses the action when merged; `/OpenAction`, `/PageMode`,
  `/ViewerPreferences`, the structure tree and article beads are not carried. (c) The merged name tree is one flat leaf
  (valid, large for tens of thousands of names). (d) Not driven in the GUI by hand. (e) merging when the CURRENT document is encrypted: done in round 17 (S17-ENC-MERGE below).
- [x] **S17-ENC-MERGE (round 17, owner decision: ask each time):** merging while the CURRENT document is encrypted
  raised `ValueError: document closed or encrypted` (a KEEP snapshot reopened without authenticating). Fixed: the
  merge (into the current tab and as a new file) asks in zh-TW whether the result keeps the document's encryption and
  permissions (the container is an emptied authenticated clone, so passwords and permissions are exact) or is
  unencrypted; cancel changes nothing; undo, Save, Save As keep following the chosen encryption. Tests in
  `test_pdf_merge_workflow.py`, `test_save_prunes_orphans.py`. See PITFALLS S17-ENC-MERGE.
- [x] **S17-INSERT-NAV (round 17, owner decision): Insert pages from file brought only the links across; the source's
  bookmarks and named destinations were lost and the document's own page labels slid off their pages.** Fixed:
  `NavigationGraft(into_existing=True)` (same graft as merge, one chokepoint) appends the source's nested bookmarks, merges
  its names into the document's name tree (the document's name wins, the source's is renamed `name.2`, links follow)
  and rebuilds the labels of the whole document so every label stays on its page and the inserted range keeps the
  source's labels; undo restores all three exactly (whole-document snapshot). Tests in `test_merge_composition.py`.
  See PITFALLS S17-INSERT-NAV.
- [ ] **S17-INSERT-NAV follow-ups (open):** (a) `insert_blank_page`, `delete_pages` and `move_page` leave `/PageLabels`
  indexed by position (labels slide off their pages); no owner decision yet. (b) The source's bookmarks are appended at
  the end of the outline, not at the insert position. (c) A document whose name tree is unreadable gets no imported
  names (named links become explicit). (d) Not driven in the GUI by hand.
- [x] **F16-COPY-1 (round 16): browse copy over a line drawn as one text show copied only the first word, or nothing.**
  Run-mode grouping gives a click on any word of a proven show `target_span_id` = the show's first word (the edit
  target); the drag start, drag end and char context used it as a location. Fixed: `TextHit.hit_span_id` (the run
  under the point), read by `PDFModel._browse_span_id` / `_browse_run_at_point_unrotated` in
  `get_text_selection_lines`, `get_text_selection_snapshot_from_run`, `get_char_context_at_point`; the view stores
  `hit_span_id` as the drag start. Tests in `test_text_selection.py` (`test_grouped_show_*`) and
  `test_browse_selection_gui_regressions.py`. See PITFALLS F16-COPY-1.
- [x] **F16-COPY-2 (round 16, was the F16-COPY-1 follow-up): browse drag copy dropped every inter-word space and Hebrew/Arabic lines copied nothing.**
  'Invoice number 4711' copied as 'Invoicenumber4711', a TJ-kerned line as 'Kernedgapwords', '10 kg item' (no-break space) as
  '10kgitem'. The gap is a whitespace glyph in MuPDF's text that no run owns. Fixed in `get_text_selection_lines` with the
  Qt-free `model/selection_text.py` (`whitespace_chars`, `whitespace_between_runs`: the page's own whitespace glyph between two
  consecutive selected runs, so nbsp / combining text copies as `page.get_text` reads it). The same pass fixed the boundary clip:
  `clip_directions` flips 'from the pointer onward' for right-to-left runs and the bottom-to-top quarter turn (a right-to-left
  line used to copy nothing, a cross-run drag on a 270-degree run copied the wrong glyphs). Tests in `test_text_selection.py`
  (`test_whole_line_drag_copies_the_page_text_including_gaps`, `test_rtl_partial_drag_*`, `test_vertical_run_cross_run_*`,
  `test_selection_text_helpers_edges`). Open: two runs far apart on one visual line with NO whitespace glyph between them
  (a table gap) still join without a separator, as `page.get_text` gives no space there either. See PITFALLS F16-COPY-2.
- [x] **F17-COPY-180 (round 17): browse copy and the double-click char context read every word of a /Rotate 180 page backwards, and Hebrew on a /Rotate 90/270 page letter-reversed.**
  F16-COPY-2's reading-direction model missed the half turn and right-to-left text on a quarter turn: a whole-line drag on an upright
  /Rotate 180 line copied 'olleH evarb wen dlrow', a two-line drag clipped the wrong half of each boundary word. Fixed in
  `model/selection_text.py` (`reading_sign` = rotation sign x script, new `order_run_glyphs`) and
  `PDFModel._get_chars_in_run_unrotated`. Tests: the page-/Rotate x Latin/Hebrew matrix in `test_text_selection.py` and a number
  double-click case in `test_numeric_token_selection.py`. Open (not changed): Tier 0 `_tier0_target_from_resolve` orders a
  multi-run line by `origin.x`, so its `run_join` candidate text is reversed on a /Rotate 180 line (the dict-line proof refuses 180
  by design; downstream effect not probed). See PITFALLS F17-COPY-180.
- [x] **F17-COH-1 (round 17): undoing a page rotation kept the rotated page size, so the restored page overlapped the next page (also after a zoom) and clicks low on it hit the next page.**
  Undo/redo dropped the page-size cache only for structural commands (page count/order), and the non-structural refresh only
  re-rendered into the old slot. Fixed: `SnapshotCommand.changes_page_geometry` (structural types + rotate/straighten) and
  `PDFController._command_changes_page_layout`, which clears the cache and rebuilds the scene on undo/redo. Guard: AST scan that
  every forward op that drops the cache is a page-geometry command. Tests `test_04h`/`04i`/`04j` in `test_multi_tab_plan.py`.
  Open: straighten is included defensively (no size change measured). Undo/redo have no editor gate before they mutate, unlike
  zoom, so a toolbar Undo of a rotation (as of any structural step) with an inline editor open settles the editor inside the refresh. A
  verified edit committed there would clear the redo stack. This follows from the code and was not probed; adding the gate is an
  owner decision. See PITFALLS F17-COH-1.
- [ ] **F17-COH-5 (round 17, OWNER DECISION NEEDED, code not changed): the toolbar 「顯示/隱藏註解」 toggle writes a hidden flag into the
  live document, outside the undo / dirty / thumbnail pipeline, and the next unrelated save persists it.**
  `AnnotationTool.toggle_annotations_visibility` sets/clears `PDF_ANNOT_IS_HIDDEN` on every Text/FreeText annotation of the
  live document (and `update()`s it); the controller only re-renders. Measured (record repro/round17_F17_COH_5.md): after
  Hide the session is NOT dirty, `can_undo()` is False, the file-source thumbnail keeps the annotation (48.05 vs 10.84
  fresh) while view and print hide it (11.08), and an unrelated edit + Ctrl+S writes flags 6 (HIDDEN|PRINT) into the file
  (page darkness 47.86 -> 11.08). The toolbar checkbox is one QAction for all tabs while the flags are per document.
  Intent is undocumented (FEATURES.md only says 'visibility toggle behavior'; the only test checks the flag bits; no decision
  covers it). Same-class audit: every other `AnnotationTool` write the controller performs goes through a `SnapshotCommand`
  (`_record_annotation_mutation` and the `add_*` methods); the watermark mutators record no command either but keep a
  per-session modified flag in the tool (`has_unsaved_changes`), which the toggle lacks. Options: (A) a view-only
  preference, never written to the file (per-session state; hide at render time or restore the flags around every
  save/print/export; open sub-questions: which annotation kinds hide (today only Text/FreeText), whether print, the
  clipboard snapshot and thumbnails follow, per-tab checkbox state); (B) an undoable document edit (one `SnapshotCommand`
  over the affected pages, dirty, `_invalidate_thumbnails`, checkbox derived from the active document's flags on tab
  change/undo/redo); (C) the watermark pattern: written and dirty (tool-owned modified flag, thumbnails invalidated) but
  not undoable. Nothing is implemented; do not guess.
- [x] **F17-COH-2 (round 17): a watermark this build saved came back on reopen ON TOP of its own baked copy, so view and print drew two copies while the file held one, each Ctrl+S after a reopen baked one more, and removing or changing the watermark could not take the saved copy away.**
  The save bakes the list into the file and stores it in the attachment; the reopen restored the list as overlay / print stamp /
  next bake over the still-baked ink. Fixed: the renderer marks its ink (`q /Artifact <<... /PdfEditorWatermark <id>>> BDC ... EMC Q`)
  and `WatermarkTool.on_session_open` takes the marked copy of every restored watermark out of the live document
  (`strip_marked_watermarks`), so a reopened session is the unbaked session M9-2 keeps; `build_working_doc_for_optimized_copy`
  no longer bakes again onto a clean session's file. Real-app probe: view = file = print = thumbnail over three sessions.
  Tests in `test_watermark_save_noop.py` and `test_text_commit_persistence.py`. Open: (1) ink baked before the mark existed
  (older builds, this build before F17-COH-2) still doubles on reopen (owner-accepted F15-G5-GEOM, no migration); (2) only the
  pages the stored list names are searched (a page another tool moved keeps its copy); (3) a page inserted from the same file
  onto a covered page draws twice until save + reopen. See PITFALLS F17-COH-2.
- [ ] **F17-COH-2 found in passing (open): detaching a tab drops the session's unsaved watermark changes.**
  `SessionTransferPayload` carries the document bytes but not `WatermarkTool`'s list, and the receiving window restores the
  list from the attachment in those bytes. Measured (model level): a watermark added and not yet saved is gone in the new
  window; a saved watermark removed and not yet saved comes back there. Pre-existing (the payload never carried tool state).
  Fix direction: carry `get_print_watermarks()` in the payload and let the receiver adopt it (and its modified flag) instead
  of the attachment.
- [ ] **F17-COH-2 found in passing (open): a secure save (garbage=4) of a watermarked session merges two pages' byte-identical
  content streams, after which undo of the Tier 0 edit is refused (`tier0 inverse patch stale`).** Two identical Tier 0 pages,
  watermark on page 1, edit page 1 and save (secure), reopen, edit page 1 back to page 2's exact text, Ctrl+S with
  `secure_save_required`: undo returns False. The same with the open-time watermark strip disabled; a one-page file or an edit
  that does not recreate page 2's bytes keeps undo. Not investigated further (the prepared-clone recovery path of
  `_atomic_full_save`).
- [x] **F17-COH-3 (round 17): a watermark was bound to a page NUMBER, so after a reorder, delete, insert or merge it sat on whatever page now held the number (view, print, saved file), and a deleted page left a number that named no page.**
  Fixed: `PDFModel._pages_restructured(origins, old_count=)` is the one chokepoint (delete / move / insert blank / insert from file /
  merge into the current document through `replace_active_document_from_snapshot(page_origins=)`); `WatermarkTool` keeps an id per
  live page and the ids each watermark covers and derives the stored `pages` from them. A watermark whose pages are all gone is
  hidden (not listed, drawn, saved or editable) and comes back whole with undo. The page identity rides in `DocSnapshot.page_state`
  (captured by `_capture_doc_snapshot`, restored by `_restore_doc_from_snapshot`), so undo / redo / rollback return the exact lists,
  also for a watermark added after the op. The watermark panel is refreshed from `_invalidate_active_render_state(clear_page_sizes=True)`.
  Guards: `test_04l` / `test_04m` (source scans), `WatermarkTool._reconcile` (logs and falls back to the numbers). Same class, fixed
  with it: the page-indexed maintenance bookkeeping (`pending_edits`, `fidelity_protected_pages`) now follows its page too (see the
  2026-10-06 item "`delete_pages` never remaps ..." below). Tests: `test_tool_extensions.py`, `test_multi_tab_plan.py` (04k-04n),
  `test_pdf_merge_workflow.py`, `test_text_commit_maintenance.py`, `test_watermark_save_noop.py`. See PITFALLS F17-COH-3.
  Side effect handled: the panel refresh also runs for rotate / straighten (same flag), so `populate_watermarks_list` keeps the selection when no row changes (`test_04o`).
  **Owner question (not built):** the dialog's "all pages" stores explicit numbers, so a page inserted or merged in later is not
  covered. Options: (a) keep (today, pinned by `test_an_all_pages_watermark_does_not_grow_onto_new_pages`); (b) store an
  "all pages" flag and let new pages inherit it; (c) ask on insert / merge. Open besides: watermark add / remove / update have no
  undo entry; tab detach does not carry the list (item above).
- [x] **F17-COH-4 (round 17): "export pages as PDF" and "merge into a new file" left out the pending watermark that view, print, image export and Save all show.**
  Both copied pages out of the unbaked live document. Fixed: `ToolExtension.prepare_derived_document` (single call
  `PDFModel._prepare_derived_document`), run by `export_pages` (PDF branch) and `compose_merged_document` (bakes by default;
  `bake_watermarks=False` for the merge into the current document). The watermark tool remaps its list to the output's page numbers
  and runs the same `_bake` as the save clone (marked ink + attachment), so a reopen draws one copy. Guard: AST scan that every
  `save_external_document` writer reaches the bake. Tests: `test_merge_composition.py`, `test_pdf_merge_workflow.py`,
  `test_watermark_save_noop.py`. See PITFALLS F17-COH-4.
- [x] **F17-COL-1..4 (round 17): the consented rebuild ("改用重建文字…", `legacy_redact_reinsert`) and the same-page drag drew the text they wrote again as plain RGB fill.**
  Invisible OCR text (`3 Tr`) became visible over the scan (the edited words and the OCR line replayed beside them), an edited
  or replayed run left its optional-content layer (drawn with the layer off), CMYK / K-only black / gray / Separation / Indexed
  colour became RGB, `/ca` alpha and blend modes were dropped and outline text became solid fill; live and after save. Fixed at
  one chokepoint: `model/text_paint_state.py` captures every text show's paint state before the rebuild erases anything
  (`PageTextStates`; a scratch copy drawn one fill colour per show maps glyphs to shows when the page holds several states) and
  `paint_state_applied` wraps every live-page write of the rebuild (edited text, replayed neighbours, push-down) in the
  source's colour space, render mode, ExtGState and `/OC`, read back before it counts. A state the writers cannot reproduce
  (clip modes 4-7, Pattern colour, stroked text under a scaled CTM, a soft mask on text that moves, mixed states) refuses with
  `TEXT_STATE_NOT_REPRODUCIBLE` before anything changes; a cross-page move refuses invisible / outline / translucent / layered
  source text (its destination is a plain text box). Tier 0/1 unchanged. See PITFALLS F17-COL-1..4.
- [ ] **F17-COL follow-ups (open):** (a) owner question: a cross-page move still turns a gray / CMYK / spot / ICC colour into
  the destination text box's RGB colour (the box is RGB-only; its later move/rotate redraws it from its stored RGB style).
  Accept and document, or refuse non-RGB colour too? (b) A rebuild still drops non-OC marked content (`/MCID` structure,
  `/Artifact`, `/ActualText`): the rewritten run leaves the structure tree, as before (an MCID cannot be reused). (c) An
  invisible-text edit now commits invisibly: after the consent nothing visible changes (consider a notice). (d) A paragraph
  edit whose runs draw the same RGB colour from different colour spaces (`0 g` beside `0 0 0 rg`) refuses, because the one
  writer colour cannot be mapped back (edit run by run instead). (e) DeviceGray black (most Office text) is not "plain": every
  such rebuild goes through the wrapper and, on a page that mixes gray and RGB text, through the scratch tagging (one page
  copy + one extraction per rebuild). Not eyeballed in the GUI.
- [x] **F16-PASTE-1 (round 16): a pasted control character in a new text box lost the text after it (NUL) or drew a replacement glyph (VT, other C0/C1).**
  `_textbox_markup` put the raw string into the htmlbox HTML; MuPDF stops at NUL and draws the other control codes as
  U+0239. Fixed with `text_normalization.strip_unrenderable_controls` (C0/C1, DEL, noncharacters removed; CR LF / CR
  become LF; tab and LF kept) at `_insert_textbox_visual_content` (add, move, rotate; the markers store the cleaned
  text), `_textbox_markup`, `PDFController.add_textbox` (control-only paste = silent no-op) and the watermark
  chokepoint (`_coerce_wm`, `add_watermark`). Owner-visible: silent removal at the model chokepoints; the inline editor now says so at paste time (S17-PASTE-NOTICE). Tests in
  `test_add_textbox_atomic.py`, `test_text_normalization.py`, `test_security_watermark_coercion.py`,
  `test_text_edit_refusal_messages.py`. See PITFALLS F16-PASTE-1.
- [x] **F16-PASTE-2 (round 16): an image inside pasted HTML became U+FFFC and was committed as a dashed "OBJ" box (edit-existing after a consent that named only the missing font; add-textbox with no prompt).**
  Fixed: the inline editor pastes plain text only and drops U+FFFC (`InlineTextEditor.insertFromMimeData`);
  `strip_unrenderable_controls` removes U+FFFC for text boxes and watermarks; `_is_identityless_placeholder` includes
  U+FFFC (untouched: named in the consent dialog, typed: refused) and `_verify_rebuild_edit` refuses an unacknowledged
  placeholder before the lossy-layer comparison (htmlbox round-trips U+FFFC, so that comparison never saw it).
  Tests: `test_inline_editor_paste.py` and the U+FFFC cases in `test_edit_text_helpers.py`, `test_text_normalization.py`,
  `test_add_textbox_atomic.py`, `test_text_edit_refusal_messages.py`, `test_security_watermark_coercion.py`. See PITFALLS F16-PASTE-2.
- [x] **S17-PASTE-NOTICE (round 17, owner decision 2026-10-12): a paste into the inline text editor silently dropped images and (later, in the model) control characters.**
  `InlineTextEditor.insertFromMimeData` now strips the control characters at paste time (the same set the model strips,
  one definition in `utils/text_chars.py`) and drops image anchors, then emits `paste_cleaned(controls, images)`;
  `TextEditManager._on_editor_paste_cleaned` shows a zh-TW status-bar message (`paste_cleaned_notice`, 4 s: controls,
  images, or both, with counts). A clean paste, CR LF, tab and CJK say nothing. A browser copy (text/plain without the
  image next to text/html with it) is detected too. Tests: `test_inline_editor_paste.py`,
  `test_text_commit_editor_mouse_gestures.py` (`test_pasting_controls_and_an_image_*`). Open: the watermark dialog's own
  text field still takes a rich paste and relies on the model strip with no notice. See PITFALLS S17-PASTE-NOTICE.
- [ ] **Paste image as an image object (owner, future feature, S17-PASTE-NOTICE):** a pasted image is dropped (with a status-bar
  notice) and leaves its surrounding spaces; offer pasting an image from the clipboard as a PDF image object instead.
- [ ] **F16-PASTE-2 follow-up (owner, optional):** the edit-existing consent dialog still names only the
  missing-font reason for a TYPED placeholder (the rebuild is refused after the consent).
- [ ] **F16-PASTE-1 follow-up (open, not measured on a real clipboard):** a real Windows CF_UNICODETEXT is
  NUL-terminated, so an embedded NUL may never reach the editor from a copy; only the injected-QMimeData repro showed
  it. Private-use characters in a new text box are drawn blank and read back as NUL in the text layer (accepted for
  consented rebuilds, OD-UNI1-COMMIT; not sanitized here).
- [ ] **F15-1 follow-up (optional UX):** keep the object selection across a pure zoom by re-resolving it and redrawing the
  overlay after `initialize_continuous_placeholders` (the document did not change), instead of dropping it.
- [x] **GATE16-1 (round 16 gate): upright text on a /Rotate 180 page had its char, word and search boxes 0.64 em off the ink,
  and the `test_font_stream_compaction.py` `[*-180]` cases failed only after another test built a `PDFModel`.** Under the
  production `small_glyph_heights` flag PyMuPDF 1.27's `JM_char_quad` treats a (-1, 0) line as a left-right mirror, so a
  180-degree glyph's box is reflected about its baseline: a click on the top or centre of the text missed
  (`get_text_info_at_point` returned `None`), and search highlights and the engine's glyph boxes were off by the same amount.
  Fixed once in `model/page_content_text.upright_glyph_boxes` (MuPDF quad upside down but PyMuPDF quad upright -> reflect),
  applied by `content_text`, `visible_text` (all rawdict reads in `text_commit/verify.py`), `PageInterpretation.rawdict` and
  `visible_search` (search tool). Suite hygiene closed at the same time: `test_scripts/conftest.py` pins the production
  PyMuPDF text flags at import and around every test, and the compaction test judges placement by rendered ink. Tests:
  `test_text_geometry_page_rotation.py` (`test_upright_180_*`, mirror guard, verify guard), `test_pymupdf_flag_hygiene.py`,
  `test_environment_pins.py`. See PITFALLS GATE16-1.
- [ ] **GATE16-1 follow-ups (open):** (a) CLOSED by GATE16-1a (round 17): the five script modules call `logging.disable` only under `if __name__ == "__main__"`, `conftest.py` has an autouse `_logging_enabled` fixture, and `test_pymupdf_flag_hygiene.py` guards the source; see PITFALLS GATE16-1a. (b) CLOSED by GATE16-1b (round 17; test isolation only, no product change): the I-beam `[0]` cases of
  `test_text_commit_editor_mouse_gestures.py` failed only after `test_multi_tab_plan.py` because the `mvc` fixture teardown's
  `view.close()` was vetoed by the test's own simulated running job (monkeypatch still active) and the surviving visible
  `PDFView` took every offscreen `QTest.mouseMove` of the next test (the offscreen platform hands a move to the first
  exposed window that holds the point). `mvc` / `mvc_legacy` now tear down with `dispose_pdf_view` (hide + `deleteLater`),
  and an autouse `_no_stray_gui_state` guard in `test_multi_tab_plan.py` fails any test that leaves a visible `PDFView` or an
  override cursor (it also caught both `test_mt2_*` close tests). See PITFALLS GATE16-1b. (c) not corrected by GATE16-1:
  the `"blocks"` extraction option and `clip=` plain-text selection of upside-down text (overlap still met). (d) found by
  GATE16-1b, not fixed (product code): `ThumbnailCoordinator._worker_finished` posts `QTimer.singleShot(0, lambda ...)` and
  `_thread_finished` calls `thread.wait(1000)` on a child `QThread`; a view destroyed before that timer fires raises
  "Internal C++ object (QThread) already deleted" (seen in `test_multi_tab_plan.py` `test_13` .. `test_16` before
  `dispose_pdf_view` pumped the loop). GATE15-3 class through a timer; the app destroys its view only at exit. Fix would be a
  bound `@Slot` carrying the token, or a `shiboken6.isValid(thread)` guard, as for the render coordinator.
- [x] **F15-4 (round 15, merged with F15-G7): after any free rotation of an app image, Move/Resize/Rotate returned False and
  Delete removed only the hidden marker (reported success, image stayed drawn, then hit as `native_image`).** The marker
  kept the REQUESTED rect: the absolute-rotation branch re-resolved with the pre-rotation rect and old angle and fell back
  to the old rect; the delta branch never updated the rect; a near-45-degree resize stored the request; and
  `add_image_object` stored the 4:3 default insert rect around a letterboxed image (any non-4:3 picture was broken at
  insert). Fixed with one chokepoint, `_sync_image_marker_to_drawn` (re-reads the rewritten placement by stream/`Do`
  slot and stores its drawn AABB + angle); `add_image_object` stores the bbox of the one placement it added. Behaviour
  change: an app image's hit bbox is now the drawn AABB (as for native images). Tests in `test_image_objects_model.py`.
  See PITFALLS F15-4.
- [x] **F15-4 follow-ups ((b) DONE round 17, D-OBJ-FRAME):** (a) DONE round 16 decisions pass (D-OLD-MARKERS, owner: repair + message):
  an old marker (pre-rotation rect with the rotated angle, or the 4:3 rect around a letterboxed image) is re-resolved when
  exactly one same-digest, same-angle, same-centre placement exists and no other marker claims it; otherwise
  Move/Rotate/Delete refuse with one zh-TW message and Delete never removes the marker alone. See PITFALLS
  D-OLD-MARKERS. (b) DONE round 17 (D-OBJ-FRAME): the Controller names a refused object to the View
  (`PDFView.note_object_op_refused`, valid inside `_emit_object_op`) and the View rebases / rotates its frame only for the
  accepted ids; a batch move that partly refuses still records the moved ones as one undo step (intended, pinned). Open
  residue: Delete clears the selection whatever the outcome (see PITFALLS D-OBJ-FRAME "Not fixed / scope").
- [x] **F15-G6 (round 15; the `insert_text` half of F15-G1-UU): a watermark, OCR text and the text-edit `insert_text` fallbacks were drawn at 2x position and size on a `/UserUnit 2` page.**
  `Page.insert_text` takes coordinates and a font size in UNSCALED user units while `page.rect`, `get_text` geometry and
  every model coordinate are already multiplied by `/UserUnit` (a MediaBox 300x400 + `/UserUnit 2` page: a 48 pt
  watermark was drawn at 96 pt and clipped at the right edge to `WMA`; an OCR word requested at (10,10,120,30) landed at
  (20,27,214,63)). Fixed at one chokepoint: `transforms.insert_text_page_space(page, point, text, *, fontsize, morph=None, **kw)`
  multiplies the point, the font size and the morph pivot by `transforms.shape_writer_scale(page)` (`1 / UserUnit`; exactly
  1.0 on a unit page, for an absent, non-numeric, zero or negative `/UserUnit`). It is now the ONLY `insert_text` call in
  `model/ controller/ view/ utils/ src/` (AST-guard test), used by `apply_watermarks_to_page` (live overlay, save, print
  helper), `apply_ocr_spans`, `_insert_tiny_plain_text` and the three `pdf_text_edit.py` fallbacks (`_push_down` last-resort,
  protected-span replay candidates, the fast insert path). Tests: `test_watermark_rotated_pages.py` (ink equals the unit
  page of the same displayed size: uu2 / uu0.5 / CropBox / negative MediaBox x 5 placements; font size and full text kept),
  `test_ocr_model_insert.py` (4 `/UserUnit` rows, position and glyph size), `test_text_commit_visual_frame.py` (chokepoint
  vs a unit-scale twin at 7 shapes incl. rotated, morph pivot, `rotate=` pass-through, scale values, the AST guard, the
  tiny-text fallback). Owner-visible: a file saved by an older build with a watermark on a `/UserUnit != 1` page has the
  wrong-place ink baked in (the restored overlay is drawn at the right place, so such a page shows two copies on
  reopen, as with F15-G5). Still open: a ROTATED `/UserUnit` page - `visual_to_unrotated_point` goes through
  `page.derotation_matrix`, which drops `/UserUnit` (the `geometry.py` item below); the strict-xfail
  `test_user_unit_rotated_page_gets_the_watermark_an_upright_twin_gets` marks it. See PITFALLS F15-G6.
- [ ] **F15-G1-UU (remaining half, open, pre-existing): PyMuPDF's other Shape-based writers ignore `/UserUnit`.**
  `insert_textbox` and `draw_rect` still draw at 2x on a `/UserUnit 2` page (`draw_rect(10,10,50,50)` lands at
  (9,0,91,51)); no product code calls them today (the AST guard also forbids a raw `insert_textbox`), so add them to
  `transforms.py` next to `insert_text_page_space` if one is ever needed. `insert_htmlbox` is right on an unrotated
  `/UserUnit` page. (The `AnnotationTool` half is fixed: F15-G1-UU-ANNOT below.)
- [x] **F15-G1-UU-ANNOT (round 17): `AnnotationTool` and the app rect object drew, picked and moved at the wrong place on a ROTATED `/UserUnit != 1` page.**
  MediaBox 300x400 + `/UserUnit 2` + `/Rotate 90/180/270`: `add_rect(30,50,90,80)` inked at (428,48,492,82) / (328,448,392,482) / (28,348,92,382) instead of (28,48,92,82), and the highlight, underline, strikeout and note went the same way; at `/UserUnit 0.5` nothing was drawn. Cause: the write sites mapped the request with `page.derotation_matrix`, which drops `/UserUnit`, while `add_*_annot` reads true unrotated space. Fixed: `_derotate_rect`, `_derotate_point` and `_displayed_rect_to_quad` use `model.geometry`; the new Qt-free `model/annot_geometry.py` reads and writes a Square/Circle/Link `/Rect` raw through the page frame (`annot_page_rect`, `set_annot_page_rect`) for `_pin_outer_rect` (redaction restore), the app rect object's pick, move and delete, and the image marker. On such a page `add_*_annot` (true unrotated space) and `Annot.rect` / `set_rect` (PyMuPDF's `/UserUnit`-less derotated space) are two spaces, so Square/Circle/Link consumers read the raw `/Rect` through the frame; the Text/Note pair (`Annot.rect * page.rotation_matrix` in `get_all_annotations`, `set_rect(derotation)` in `move_annotation`) is self-consistent within the derotated space and was already right (a note's raw `/Rect` is not the drawn rect: NoRotate). Tests: `test_annotation_rotation.py` (ink vs the unrotated twin at 3 rotations x 2 units x 5 kinds, note read/move, restore), `test_object_manipulation_model.py` (rect object draw/pick/move/delete). Not eyeballed in the GUI. See PITFALLS F15-G1-UU-ANNOT. Still open: the app TEXTBOX marker is created from VISUAL numbers by `add_rect_annot` and moved by `set_rect`, two different spaces on such a page; it is hidden and picked by its payload there (F15-G1-UU-ROT), so nothing shows.
- [x] **F15-G1-UU-ROT (round 16): on a ROTATED `/UserUnit` page `insert_htmlbox` (text rebuilds, app textboxes), `insert_image` and the visual-to-unrotated mapping dropped the scale.**
  MediaBox 300x400 + `/UserUnit 2` + `/Rotate 90/180/270`: `add_textbox` at (10,10,200,60) inked at (23,31,161,58) (2x glyphs, offset), a bottom-right box drew nothing, `/UserUnit 0.5` drew nothing. Fixed at the chokepoints:
  `transforms.pymupdf_writer_matrix` (`~base x transformation_matrix`: translation plus `1 / UserUnit`) behind
  `shift_rect_for_pymupdf_writers`; `insert_htmlbox_tracked` lays out in the unscaled rect and redirects `show_pdf_page` to
  the placed one; `model.geometry` takes the quarter turn from the page frame (this also closes the unclipped-CropBox
  offset of the old geometry item); `PDFModel._visual_rect_to_unrotated_rect` delegates to it; a textbox marker on such a
  page is picked by its payload rect. Ink tests: add/move textbox, legacy text rebuild, app image, writer rect round trip,
  geometry round trip. Not eyeballed in the GUI. See PITFALLS F15-G1-UU-ROT.
- [x] **F15-RTL-ORDER (round 16): Hebrew/RTL runs were indexed in visual (x-sorted) order, so every RTL rebuild drew the word mirrored.**
  Fixed: the run parser still segments by x but emits a right-to-left run's text in MuPDF's source (LOGICAL) order and
  numbers a line's runs in that order too (`span_idx` = reading order; paragraph / selection / colour joins follow);
  Tier 0 never targets right-to-left text. Index contract: text logical, bbox/origin visual. See PITFALLS F15-RTL-ORDER.
- [ ] **F16-RTL-RESIDUAL (found in the F15-RTL-ORDER fix, open):** (1) Tier 0 has no operand reordering, so Hebrew/Arabic edits
  always take the consented legacy rebuild (`_tier0_target_from_resolve` returns None); (2) table-cell rules (a)/(a2) and
  `_merge_same_baseline_units` order cells by x, so an RTL table row is not cut into cells and a split RTL line merges in
  x order [fixed in round 17 (F16-RTL-CELLS): a line with RTL letters is cut by the gap between VISUAL neighbours, a block's
  reading direction is its first strong character (XOR upside-down), and the cells of a Hebrew row come out right cell first;
  see PITFALLS F16-RTL-CELLS]; (3) [fixed by F16-COPY-2: browse-selection clipping now follows each run's reading direction]; (4) mirrored brackets in mixed text are whatever MuPDF reports; (5) [fixed by D-RTL-GROW: a rebuilt RTL word keeps its right edge and grows left].
  (6) open: a Hebrew word can still be indexed as two runs (`עול` + `ם`) when a trailing-space glyph box overlaps its final
  letter and sorts between them in `_parse_runs_from_raw_line`, so the paragraph text shows a space inside the word.
- [x] **D-RTL-GROW (owner decision after round 15, built in the round 16 decisions pass):** a longer RTL (Hebrew/Arabic)
  word keeps its RIGHT edge and grows to the left; a shorter one shrinks toward that edge. Every route that redraws an RTL
  run agrees (consented rebuild, htmlbox route, protected-neighbour replay, push-down) on every page turn; the wall and the
  neighbour check look LEFT (left page margin as the floor). Rule (`model/rtl_text.grows_right_to_left`): no RTL letter =
  LTR as before; RTL letters only = RTL; both = the paragraph's base direction (first strong character of the block). Open:
  a digits-only run in a Hebrew paragraph stays LTR (as Tier 0 treats it); not checked in the real GUI. The legacy htmlbox
  live preview now keeps the right edge too (round 17, D-RTL-PREVIEW; frame minimum-width padding at 0/180 not checked). The direction of an edit needs the old run AND the typed text to be RTL (round 17, F17-RTL-LATIN: a Hebrew word retyped as 'Hello world.' is LTR; a Latin run retyped as Hebrew stays LTR). See PITFALLS D-RTL-GROW, D-RTL-PREVIEW, F17-RTL-LATIN.
- [x] **F14-ANCHOR-STALE (round 16, fixed):** the anchor migration (`_choose_anchor_run`) and the hit-test stale re-bind (`_stale_anchor_rebind_run`) no longer pick a run on distance alone; a heading re-inserted as several runs drops its anchor and a click opens the run under the cursor. Tests in `test_edit_text_helpers.py`. Follow-up fixed in round 17 (S17-ANCHOR-JOIN, owner decision ANCHOR-FRAGMENTS): the runs one app edit wrote on one baseline reopen and commit as ONE box (`model/joined_edit_runs.py`). Open: the record is session-local (a saved and reopened file shows the fragments again); a re-edit whose fragments land on a different line stays split; not eyeballed in the GUI.
- [ ] **F14-VF4-WRAP-REFLOW (reflow part open; the hyphen part is settled, see D-HYPHEN-WRAP below):** instead of
  shrinking or refusing a word that outgrows its slot in a paragraph, reflow the rest of the line / paragraph. Planned in
  `plans/paragraph-reflow.md` (owner answers recorded; build after the adversarial loop converges); shrink / refuse stays
  in code until then.
- [x] **D-HYPHEN-WRAP (owner decision after round 15, round 16 decisions pass):** a wrap at the right-hand neighbour may
  break a word after an existing hyphen (U+002D, U+2010; `multicolumn.pdf` `Two-Column` -> `Two-Colunm` gives `Two-` /
  `Colunm`, hyphen at the end of line 1). U+2011 never breaks, no hyphen is inserted, a word without a hyphen keeps
  shrinking (floor 50 %) or being refused, and with no room for a second line the word is not broken either. The behaviour
  was MuPDF's line breaker already; now pinned by `test_scripts/test_hyphen_wrap.py`. One code change: a hyphen that
  OPENS a word is glued to it (`_latin_word_html`), so a wrap never strands a line of just `-`. Open: MuPDF also breaks
  after `/` and en / em dashes (unchanged, not a hyphen); rotated pages not checked in the GUI. See PITFALLS D-HYPHEN-WRAP.
- [x] **F13-VF-4b (round 16, fixed for in-place quarter-turn rebuilds): a vertical htmlbox grew to the page edge and the
  longer word overprinted the next run on its column, reporting SUCCESS.** `_vertical_neighbour_limit` (the vertical
  twin of `_right_neighbour_limit`) caps the box at the next untouched run along the reading direction; text that
  does not fit before it is shrunk to at most half size or refused (`TEXT_DOES_NOT_FIT`, rolled back), and every
  in-place vertical insert goes through the `_new_text_overprints` guard. See PITFALLS F13-VF-4b. Tests in
  `test_edit_text_helpers.py` (`test_f13vf4b_*`).
- [x] **F13-VF-4c (round 17, S17-DRAG-GUARD, owner decision): a dragged `new_rect` edit is not capped but IS overprint-guarded**
  (horizontal and vertical). A drop that would draw the edited text over untouched text is refused
  (`DRAGGED_BOX_OVERPRINTS`, page rolled back, the user's text kept in the editor) and the Controller asks, for that one
  edit, "仍要放在這裡" (`EditTextRequest.place_anyway`: neither cap nor guard) or "取消"; no global setting; the rebuild
  consent is not asked a second time. A drop that moved more than 0.5 pt no longer exempts the overlap cluster's
  neighbours. See PITFALLS S17-DRAG-GUARD. Tests in `test_edit_text_helpers.py` (`test_s17_dragged_*`, `test_s17_place_*`,
  `test_s17_a_sub_tolerance_*`) and `test_text_edit_refusal_messages.py` (`test_dragged_refusal_*`).
- [ ] **F13-VF-4d (open): quarter-turn multi-column wraps have no cross-axis wrap floor** (the `_wrap_floor` analogue); the
  overprint guard refuses them when they would land on untouched text. A cross-page move's destination (a fresh
  `add_textbox`) is not overprint-guarded either: it is a new text box, placed where the user dropped it.
- [x] **F13-VF-3: a protected neighbour was replayed (and a pushed block re-inserted) through `insert_htmlbox(tight bbox,
  scale_low=0)`, shrunk (60 -> 43 pt, 12.82 -> 10.57 pt, 30 -> 22.31 pt) and moved, and the validator only checked the
  text was present.** Fixed (round 13): `_place_htmlbox_at_origin` measures where an oversized unwrapped box draws the
  first glyph and moves it onto the span origin, inserted with `scale_low=1`; `_validate_protected_spans` also checks a
  glyph at the span's size and origin. Residual: the substitute font face (T16-5) still differs from the original
  (PITFALLS F13-VF-3 has the pixel numbers). A very wide replay font now overflows to the right instead of shrinking.
- [x] **F13-VF-2: the legacy rebuild redacted the overlap cluster's bounding box and erased glyphs of untouched words
  outside the cluster (Awareness p1 `So-called` -> `So-call`, `health` -> `ealth`; GeoTopo p2 `direkt`, `mit`, `zu`,
  `dürfen!`), still SUCCESS.** Fixed (round 13): the rebuild and the overflow push-down erase only the glyphs they own
  (`_redact_owned_glyphs`: one point redaction per owned glyph above its baseline, line art only inside the owners'
  own boxes) and refuse with the new `untouched_text_would_be_lost` (zh-TW sentence) when a non-owned glyph is gone,
  page rolled back. Corpus sweep (every run of the first pages, legacy engine): no collateral word loss left (see
  PITFALLS F13-VF-2 for numbers). Behaviour changes: a line-art decoration spanning two cluster runs is no longer
  removed by the rebuild; a genuinely overlapping foreign glyph (LaTeX logo `L` under its `A`) now refuses instead of
  vanishing.
- [x] **F13-VF-2b (round 16): moving, rotating or deleting an app textbox object erased the page text under it.**
  `pdf_object_ops._redact_and_restore_textbox_region` redacted the whole textbox rect (repro: page text
  `UNDERLYING PAGE TEXT`, add a textbox over it, move the textbox: only `Moving box` left). Fixed at one chokepoint,
  `_erase_textbox_drawing`: the box's own htmlbox Form XObject is emptied, proven by the page losing exactly the
  stored text's characters (no marker field, so older files resolve too); when the drawing is not one form the rect
  redaction runs only if the rect holds no page text the box does not own, else the op refuses (`False`). Same class
  in `_remove_native_image_invocation`: an image's `q` block is dropped only when it paints nothing else, otherwise
  the `Do` alone. Tests in `test_object_manipulation_model.py`, `test_native_pdf_images_model.py`. See PITFALLS
  F13-VF-2b. Open: a mixed box (loose edit glyphs) over foreign page text is refused, not moved; since
  D-OLD-MARKERS the refusal shows a zh-TW message.
  Round 14 (F14-MM-1): the redaction now runs in unrotated space, so on a `/Rotate 90/180/270` page it also erases
  the page text visually under the textbox (before, that happened only at `/Rotate 0`; rotated pages instead lost text
  elsewhere and kept a ghost copy).
- [x] **F14-MM-1 (round 14): on a `/Rotate 90/180/270` page, moving, rotating or deleting an app textbox left the old
  copy drawn and erased unrelated page text.** `_redact_and_restore_textbox_region` passed the marker's VISUAL rect to
  `add_redact_annot` and `_save_overlapping_annots`, both unrotated-space. Fixed at that one helper (move, rotate,
  delete): the rect is derotated with `_visual_rect_to_unrotated_rect`, the same helper the insert uses. Tests in
  `test_object_manipulation_model.py` (0/90/180/270 x move/rotate/delete, plus a link guard). See PITFALLS F14-MM-1.
- [x] **F14-MM-2 (round 14): each app-textbox move grew the box 1 pt per side and shifted its text (-1,-1); rect and
  image objects grew once on their first move.** `get_object_info_at_point` returned the marker's `annot.rect`, which
  PyMuPDF inflates by the `/RD` inset, and the drag fed it back. The hit bbox now comes from `payload["rect"]`
  (`_app_object_true_rect`); a re-created Square/Circle keeps its saved outer rect (`_pin_outer_rect`). Tests in
  `test_object_manipulation_model.py`. See PITFALLS F14-MM-2.
- [x] **F15-3 (round 15): a rect object on a `/Rotate` 90/180/270 page could only be selected where nothing was drawn, and a drag teleported and transposed it.** The rect object's annotation IS the drawn rectangle, so its `/Rect` is unrotated (`AnnotationTool.add_rect` derotates), but `get_object_info_at_point` hit-tested the visual point against it raw and `move_object` wrote the visual destination to it raw (measured on 600x800 `/Rotate 90`: click at the drawn centre = no hit; a 20 pt right drag drew it ~500 pt away, width and height swapped). Fixed in `model/pdf_object_ops.py`: `_marker_pick_rect` maps a rect marker's `/Rect` to visual space for the hit test (and the no-payload-rect fallback of `_app_object_true_rect`), and the move maps `destination_rect` with `visual_to_unrotated_rect`, the mapping `add_rect` uses. Delete needed no change (`annot.rect` there only feeds the dirty-page queue, which reads the page index, not the rect). Tests (ink oracle, 0/90/180/270 x plain/CropBox: hit anywhere on the drawn ink, three moves, save and reopen; delete) in `test_object_manipulation_model.py`. See PITFALLS F15-3. Open: a file saved by an older build after a rect object was DRAGGED on a rotated page keeps the mangled `/Rect` (drawn elsewhere, payload rect visual); not healed. Textbox markers keep visual numbers in their hidden `/Rect` on purpose (self-consistent, never drawn); image markers hold the UNROTATED placement since F14-MM-1b.
- [x] **F14-MM-1b (round 16): app image objects on a `/Rotate` page were drawn in the wrong place; native and app
  images were hit, reported and moved in unrotated space.** Fixed at one boundary in `model/pdf_object_ops.py`:
  `add_image_object` derotates the visual rect, shifts it (F15-G4-IMG) and turns the picture by `/Rotate` so it is upright
  on screen; image payload rects and marker `/Rect`s stay UNROTATED (what discovery reports and what older builds wrote,
  so their image objects on rotated pages still resolve) and are mapped to visual for the hit test and
  `ObjectHitInfo.bbox`; native hit test, bbox and move destination are mapped with `model.geometry`.
  `ObjectHitInfo.rotation` stays the stored raw-cm angle (upright image on `/Rotate 90` reports 90, like a textbox).
  Ink tests over 0/90/180/270 x plain/crop/negmb (app: add/hit/move/rotate/save-reopen/delete, letterbox, legacy marker;
  native: hit/move/resize/delete). `/UserUnit != 1` on a rotated page is fixed (F15-G1-UU-ROT); old images already drawn sideways
  on a rotated page are not re-inserted; not eyeballed in the GUI. See PITFALLS F14-MM-1b. Measured before the fix: on a
  `/Rotate 90` 595x842 page an image added at visual (100, 200, 200, 250) was drawn at visual (592, 100, 642, 200);
  a native image on a 600x800 `/Rotate 90` page was hit only at its unrotated numbers (F15-3 repro).
- [x] **F13-VF-1: a consented legacy rebuild of a quarter-turn run inside a multi-run block (a drawing-sheet table row)
  was drawn at the block's first cell (~300 pt away on hvac-dwg p5), over the neighbour cell.** Fixed (round 13): the
  vertical no-rect branch sizes the htmlbox from the run's reopen anchor (`base_layout`), and the drag clamp fallback
  from the edited member spans, not `TextBlock.layout_rect`. Guard:
  `test_legacy_rebuild_of_quarter_turn_run_in_a_multi_run_block_keeps_its_place`. Open: `_verify_rebuild_edit` only
  checks presence inside the rect it inserted into, so a misplaced rebuild still verifies; a "landed text intersects
  the redact/anchor rect" check is a candidate guard (must not trip moves or push-downs).
- [x] **B1: an out-and-back grip drag left `editing_rect` about 0.05 pt off and the preview refused**
  (`geometry_override_present`, Apply disabled; also at rotation 0, so older than round 7). Fixed: within 0.5
  scene px of the open rect `_finish_editor_drag` restores an exact copy of `_editing_original_rect`. Guards:
  `test_grip_out_and_back_to_the_open_position_restores_the_exact_rect_and_keeps_apply[...]` and
  `test_grip_out_and_a_little_back_keeps_the_inverse_rect[...]`. Round 2 (R7-INT-1): also restored (rect and proxy
  position) whenever `_editing_position_changed` is False, closing the 1 px band at zoom >= 200 %; guard
  `test_grip_one_px_off_the_open_spot_at_214_percent_is_not_a_move_and_keeps_apply`.
- [x] **RPU-2: the origin patch was one flat ring-mean colour on striped, ruled or image backgrounds.** Fixed by
  the uniformity gate (`ring_nonuniform_pct` above 0.05 skips the patch); the proper fix is the open item
  "Proper background reconstruction" below.
- [x] **Retire the plan-mode chip (owner decision)** -- resolved (see the item in the round 6 section below).
  Plan mode paints the base frame plus the badge only; `plan_preview_chip_text` is deleted.
  `test_plan_mode_paints_the_badge_and_no_chip[...]`, `test_a_plan_mode_box_paints_no_chip_while_composing[...]`.
- [x] **Rotated-page box move** -- resolved (see the item in the round 6 section below).
  `_proxy_corner_offset` / `_proxy_visual_extent` / `_quarter_turn_proxy_layout`; grip tests run on 0/90/180/270
  (`test_text_editor_rotated_move.py`, `test_text_commit_editor_mouse_gestures.py`).
- [ ] **Retire the non-plan composing chip (owner decision; option a1).** Outside plan mode (every add_text
  box, legacy edit_text) the composing chip is the ONLY preedit echo, so it stays: `LiveTextStrip` is hidden
  for non-plan editors and `_paint_composing_frame` bypasses the native paint. Option a1: show the strip for
  add_text/legacy editors for the editor's whole life (the IME anchor then does not jump between box and strip),
  then delete the chip (`_composing_chip_parts`, `elide_composing_parts`, `_fit_edge`, the composing-chip tests).
  Not done without the owner's decision.
- [ ] **A moved add_text box paints a stale frozen snapshot of the old spot's page pixels** (`diag_f1` section 4:
  ink 965 from the old spot against 545 actually under the new spot). Not F1 (there is nothing to hide at the
  origin of a new box; the origin patch is never created for add_text), but stale page pixels show inside the
  moved box.
- [ ] **Cross-page move between pages with different `/Rotate` keeps the origin rotation** (ROT residual: the
  proxy keeps `_editing_rotation` of the page it was opened on).
- [ ] **Dead `_drag_pending` mouse-move branch in `PDFView` is untouched** (see the dead-code item below). Round
  7 only made it call the fixed `_clamp_editor_pos_to_page` and page-resolve helpers; delete it together with
  the pending-release branch.
- [ ] **The `無法套用`/`組字中` badge is now the only in-box signal in plan mode and is clipped in narrow
  editors** (about 80 px wide at 100 % on `ecc-dwg.pdf`; reworded in the round 4 item below). The strip and the
  bar reason label are the readable signals.
- [ ] **Moved rebuild re-wraps the run onto two lines (review S2, not confirmed pre-existing).** After a grip
  move plus rebuild-consent apply on the synthetic one-line Helvetica fixture, the rebuilt text comes back
  narrower and on two lines, at rotation 0 too (round 7 did not touch that path, so it is probably older, but
  nobody checked on HEAD). `test_a_rotated_grip_move_lands_where_the_box_was_dropped_and_survives_save_reopen`
  therefore compares only the first-line top-left of the ink in the unrotated frame. A line becoming two breaks
  the pdf-text-fidelity standard (visual consistency before/after); confirm on a clean base and fix.
- [ ] **The origin patch margin (1 pt, at least 1 scene px, plus up to 1 px of outward snap: 1-2 pt per side at 100 %, 2-4 pt at 50 %) can hide neighbouring vector content while the box
  is away** (review S4): a table rule, underline or strike line, or a tight-leading neighbour line inside that band around
  the span bbox disappears at the origin until commit or cancel (HDZ-1: the gate now measures the whole painted
  band at every DPR/zoom, so such a neighbour SKIPS the patch instead of being erased silently). Without the margin the CJK corpus showed glyph
  slivers outside the source span bbox (1 px at 100 %, up to 2 px at 214 %); `F1_red_margin0` pins the margin.
- [ ] **Proper background reconstruction for the origin patch (RPU-2).** The patch is one flat ring-mean colour,
  so it is only drawn when the 3 px ring around the source span is uniform (at most 5 % of the ring pixels more
  than 48 (summed r+g+b) from the ring mean; measured: white synthetic 0.00, ecc-dwg CJK run 0.003 at 100 % and
  0.004 at 214 %, 1 pt black/white stripes 1.00). On hatching, dense rules or an image the patch is skipped
  (debug log) and the source text stays visible beside the moved box until commit or cancel. Missing: rebuild the
  hidden background (inpaint from the ring, or re-render the page with the run removed) so those pages hide the
  source too.
- [ ] **A ruled line (or sparse hatch) crossing the span stays under the uniformity gate and is wiped by the flat
  patch (blind spot of the RPU-2 ring test).** The 3 px ring touches such a line only at its two ends, so
  `ring_nonuniform_pct` stays under 0.05 and the flat ring-mean patch erases the line inside the span while the
  box is away (it comes back on commit or cancel). Needs a test of the span interior, or the background
  reconstruction above. Not measured on the corpus.
- [ ] **Origin-patch build still scales with span area in its other helpers (PERF-1 residual).** The ring
  uniformity check is now O(perimeter) (< 1 ms), but `_build_background_matched_mask` still runs
  `_qimage_ring_mean_rgb` (full-outer-rect numpy mask), `_mask_leak_ratio` and `_qimage_mean_rgb` on the flat
  patch: about 55 + 80 + 40 ms on a 4320x1776 px paragraph span (zoom 4 / DPR 2), so the first grip-drag frame of
  a very large paragraph still exceeds a 50 ms budget. Shared with the editor-open path; band-based ring mean and
  skipping the leak/mean passes on a freshly flat-filled patch would remove it. Not measured end to end.
- [x] **PERS-1: Save As left the live handle on the old file, so a second tab rewriting it corrupted tab 1 (round 7, round 5).** Fixed at `save_as` (handle rebound to a private temp copy of the live doc, `garbage=0`), plus write-side guards in `save_as` and `save_external_document`; see PITFALLS. Open: the rebind is skipped (warning logged, old behaviour) if writing the private copy fails (disk full); the path map could additionally keep claiming the old path for that session. Cost: Save As of a file-backed doc serializes the live doc a second time (temp file, no memory copy). Not driven through the GUI.
- [x] **PERS-2: a failed overwrite of the open file closed the live doc first (round 7, round 5).** Fixed: `_install_stage_over_open_file` (sibling copy, close, atomic `os.replace`, rebind to a recovery copy on failure) for `_full_save_to_path` and the `save_as` prepared-doc branch; the orphan-fallback full save is no longer retried on a closed handle. Round-6 FS-1: the secure sibling `_atomic_full_save(replace_live_handle=True)` now goes through the same helper with a recovery copy of the live doc (it used to reopen the OLD target and delete the stage), and `_restore_doc_from_snapshot` opens the replacement before closing the live handle. See PITFALLS. Open: the disk-full case is covered with an injected partial `copy2` only; a failed install leaves the session on a temp-dir file (further saves are plain full saves, not incremental) until the tab is reopened; the replaced target gets directory-default ACLs. Not driven through the GUI. Round-8 LS-2: the non-open-file full-save branches (in-memory live doc after a snapshot undo/redo, Save As over an existing file, prepared-doc branch, `save_external_document`, page-image export, `headless_merge`) now stage + `os.replace` via `PDFModel._save_doc_to_user_path` instead of `doc.save(path)` straight onto the target; the incremental append stays in place by design.
- [x] **EXT-1: a second incremental save from the same live handle corrupted the xref chain (round 8).** Fixed: `save_as` swaps in a freshly opened handle after every incremental save (`_renew_handle_after_incremental_save`), and a handle that could not be replaced is marked spent so the next save is a full one. Tests in `test_save_prunes_orphans.py` walk the raw `startxref`/`/Prev` chain (and qpdf via pikepdf on `test_files/1.pdf`). Open: the tiered engine's per-handle caches are rebuilt after every Ctrl+S (as after a full save); the signed-file case is covered by the prefix + chain walk only, no PKCS#7 validator; a handle that could not be replaced is spent, and a spent SIGNED file then takes the full rewrite (fallback only; invalidates the signature); not driven through the GUI.
- [x] **ERR-1: replace + recovery reopen both failing lost the edits (round 7).** Fixed: `_rebind_to_recovery_copy` falls back to an in-memory open; if that fails too the recovery file is kept and `SaveRecoveryError` (path, `target_written`) is raised and shown verbatim by the controller (also on the close / Save All path, R8-ERR1-CLOSE: no dead Save dialog, close ignored). Dead-tab behaviour (S14-SAVEREC-DEAD-TAB, owner decision C, round 14): a lost session is a visibly dead tab - `DocumentSession.save_lost_error` (set only by `PDFModel._mark_session_lost`), `PDFModel.doc` returns `None` for it, `save_as`/`save_session_as` re-raise the error (retries keep the recovery-path message), every view-signal slot except the exempt list (`PDFController._LOST_SESSION_SLOTS`) is dropped by `_live_only`, `_render_active_session` shows the notice (tab title “（已中斷）”, status bar), Save As copies the recovery file (`copy_lost_session_recovery`), Discard keeps it until app exit. Open: not driven with a real WinError 32 lock or through the GUI (monkeypatched double failure only); an in-memory rebound session has no backing file until the next successful save-back.
- [x] **FS-2: private `live_*.pdf` / `recover_*.pdf` copies leaked after an in-memory reinstall (round 7, round 6).** Fixed: the `doc` setter retires the temp-dir file the replaced handle read (`_retire_replaced_handle`) and `_sweep_retired_live_copies` deletes it once the handle is closed (snapshot undo/redo, rollbacks, `_roundtrip_live_doc`, recovery rebinds). Tests in `test_save_prunes_orphans.py`. Not done: a crash still leaves the files in the anonymous `%TEMP%	mpXXXX` dir (no startup sweep).
- [x] **FS-3: saving back to the open file failed for paths near the Windows limit (round 7, round 6).** Fixed: staging names no longer embed the target stem (`utils/path_staging.py`), extended-length form when still too long; same fix at the optimizer's `_opt` stage and the secure `.tmp` stage. See PITFALLS.
- [ ] **FS-4 follow-up (Windows only): install saves with `ReplaceFileW` (owner decision, round 6).** The owner kept the atomic `os.replace` install (hard links keep the old content, named streams such as `Zone.Identifier` are dropped; documented in PITFALLS PERS-2). Follow-up: on Windows/NTFS use `ReplaceFileW` via ctypes in `_install_stage_over_open_file` and the same-class sites (`_atomic_full_save` secure branch, `pdf_optimizer.save_optimized_copy_from_snapshot`) to keep named streams, ACL and attributes and to allow a hidden staging file; classify `ERROR_UNABLE_TO_MOVE_REPLACEMENT(_2)` / `ERROR_UNABLE_TO_REMOVE_REPLACED` so the recovery rebind stays correct; fall back to `os.replace` elsewhere. Hard links still lose the edit with `ReplaceFileW`. Also: a crash-leftover sweep of `.<12 hex>.(tmp|install|opt).pdf` siblings must be age-gated and pattern-restricted so it never deletes another instance's in-flight save.
- [x] **LS-1: a session read clean after save -> undo -> new edit, or after evicting past the saved point (round 8).** Fixed: `CommandManager` keeps the saved STATE (top command by identity; empty base = `None`; `_SAVED_UNREACHABLE` once evicted or discarded with the redo stack) instead of a stack length, so the unsaved prompt on tab/app close and the thumbnail source choice see the true state. Tests in `test_undo_memory_budget.py`. Open: the GUI close prompt was not driven; after eviction past the saved point the session stays dirty until the next save (intended, conservative).
- [x] **SPECIAL-SIG-1: the round-6 orphan fallback rewrote signed PDFs (round 7, round 6).** Fixed: `_session_orphans_block_incremental` returns False for a document with a signed signature (fail-closed probe), so Ctrl+S keeps the signed revision as a byte prefix; the orphans stay in the appended revision. Tests in `test_save_prunes_orphans.py`. Open: no real PKCS#7 validator was run (ByteRange-digest and prefix checks only); an incremental-save exception, a `secure_save_required` latch, a watermark-overlay save or a file-backed handle that cannot save incrementally still full-rewrites a signed document (pre-existing, no warning shown). R7-1 closed: a snapshot undo/redo (in-memory handle) or a Save As of a signed document now appends via `model/signed_append_save.py` instead of rewriting (tests in `test_save_prunes_orphans.py`); R8-SIG-A closed: xref-stream sources (a file-backed live handle's trailer-`/ID` drift in the xref-stream object) no longer decline the append; R8-SIG-B closed: the file's appended xref stream no longer collides with live-allocated objects, so a second Ctrl+S (also after a Save As, and after undo) keeps appending (session floor `reserved_xref_length`, padded by the `doc` setter). EXT-2 closed (round 8): the append no longer declines on a dictionary key-order-only difference (a file carrying the `__pdf_editor_watermarks` attachment printed the inline Filespec with `/Type` last live and first after a reopen), so a signed watermark-attachment file keeps the signed prefix on undo/redo and Save As; a decline of a signed document is now logged at WARNING. Test in `test_save_prunes_orphans.py`.
- [x] **R7-2: a save racing the thumbnail file worker failed with a sharing error and rebound the session to a temp copy (round 7).** Fixed in the controller: `_background_file_readers_released` cancels and joins the thumbnail coordinator around `save`, `save_as`, the close-time saves and merge-to-new-file, then restarts an interrupted job. Open owner decision: the optimizer's process-pool initializer keeps `source_path` open for the pool's lifetime (a save over that path during an optimize run would hit the same error); options are (a) optimize a private copy of the source, (b) refuse saves to the optimize source while a submission is active. The window-modal progress dialog makes this unreachable from the main window today.
- [x] **F10-FS-1: another program rewrote the session's file; Ctrl+S reported success over foreign bytes or silently clobbered it (round 10).** Fixed for the FILE: each session keeps a `(size, mtime_ns, edge sha256)` fingerprint of the file it owns (recorded at open, carried unchanged by a tab detach (F11-OPEN-2) and re-recorded at the end of every `save_as`), and a save back to that path whose fingerprint changed raises `SourceChangedOnDiskError` before anything is touched (nothing written, session stays dirty; the controller shows the message, the close path then offers Save As). See PITFALLS. Open owner decisions: (1) **RAM isolation from foreign writers** (RESOLVED round 11: option (a), OD-FS1-LOCK item below) - the live document still reads the rewritten bytes, so the view and the unsaved edits are lost before any save (repro `p8_app_flow.py`); options (a) hold a deny-write share handle on the file for the session (Windows `CreateFile` with `FILE_SHARE_READ` only, released around every own write: Explorer / sync clients then get "file in use", like Acrobat), (b) open from a private copy or from memory (open-time copy cost up to the 512 MB cap; incremental and signed-append saves then append onto the private copy and install with `os.replace`), (c) accept and document (the save-time gate is the only guard). (2) **Lazily damaged files** (RESOLVED round 11: read every object at open, OD-FS1-READALL item below) - a file whose broken xref entry MuPDF only meets during a save is repaired mid-save and the in-RAM edits are dropped (`is_repaired` False -> True; even a raw incremental save returns normally); moving the full-save fallback out of the `except` block (it fixes the WinError 5 on the staging file) made that case report success without the edits, so it was reverted. Candidate: an object-parse pass at open so the repair happens before any edit and `_repair_doc_xref_in_memory` handles it; cost = one parse of every object per open. (3) A sync client or indexer that only touches the file's mtime (same bytes) also trips the gate: the user gets the "modified by another program" refusal and has to Save As; a whole-file hash on mtime-only changes would avoid it at a read-the-file cost. Not driven through the GUI; the gate is not covered for in-place writers that keep size, mtime and both 4 KB edges identical.
- [x] **OD-FS1-LOCK: another program could rewrite the open session's file and the live document lost its edits before any save (F10-FS-1 RAM half; owner chose option (a), round 11).** Windows: each session holds a deny-write share handle (`CreateFileW` `GENERIC_READ` + `FILE_SHARE_READ`; `utils/file_share_lock.py`) on the file it owns from before `fitz.open` until `close_session`; the app's own writes suspend it (`replace_file` for every staged install, the incremental append in `_save_as_unchecked`) and `save_as` re-syncs it (moves to the new file after Save As). Degrades with a log line when it cannot be taken (network share, file already open for writing); no-op off Windows. Behaviour change: other programs cannot save over, rename or delete an open file ("file in use"). See PITFALLS. Open: (1) the lock is released for the duration of our own write; a foreign writer that wins that window is still caught only by the F10-FS-1 gate on the next save (and not at all for the bytes our write replaces); (2) not driven through the GUI or against a real SMB share (degrade path covered by a simulated refusal); (3) a crash leaves no lock (process exit closes the handle).
- [x] **OD-FS1-READALL: a lazily damaged file was repaired by MuPDF in the middle of Ctrl+S and the in-memory edits were dropped (F10-FS-1 open issue (2); owner chose the read-everything-at-open pass, round 11).** `open_pdf` now loads every object once (`xref_compaction.read_every_object`, called from `_read_every_object_at_open` before the compaction / repair steps), so MuPDF's lazy repair happens at open, before any edit, and the existing repair round trip installs a clean memory-backed document (encrypted: MuPDF's repaired handle, `is_repaired` True right after open). The same pass feeds the LS-3 compaction verdict (no second walk). Cap: `MAX_READ_ALL_SLOTS` = 200,000 slots (~1 s; cost tracks slots, not bytes; corpus max 40,015 slots / 179 ms) plus the H10-2 unbacked-table guard. See PITFALLS. Open: (1) tables above the cap keep the old mid-save behaviour; (2) damage only in stream data is not covered (a bad stream `/Length` was probed: no repair, edit kept); (3) not driven through the GUI; (4) loaded objects stay cached for the document's life (~0.3-0.9 KB per slot).
- [x] **F11-FS-1: a signed Save As embedded another program's appended revision of the source as its signed prefix (round 11).** `_save_signed_by_appending` read `original_path`'s current bytes; the F10-FS-1 gate only guards the write target. Fixed: `_signed_append_base_bytes` keeps only the leading bytes that still match the session's `disk_fingerprint` (a foreign append is cut off, output = opened bytes + one revision); a rewritten, truncated or unreadable source declines the append and takes the existing full-rewrite path (signature warning). See PITFALLS. Not changed: RAM isolation from foreign writers (F10-FS-1 owner decision above).
- [x] **MBT-1: Ctrl+S over the open file failed with WinError 5 (and the retry too) after a text edit on a page with 2+ annotations (round 10).** PyMuPDF `first_annot`/`.next` walks leave Page<->Annot cycle garbage that keeps the file open after `Document.close()`. Fixed at the producers (`forget_walked_annot` in `_annotation_entries` and `_find_annotation`) and at the chokepoint (`utils.path_staging.replace_file`: one `gc.collect()` + retry on `PermissionError`, used by every staging `os.replace`). See PITFALLS. Not changed: other `os.replace` sites that never touch a PyMuPDF-read file (`pdf_optimizer._postprocess` repack) keep the plain call.
- [x] **F10-UNI-1: a consented rebuild saved `·` for every non-Latin-1 character and reported SUCCESS (round 10).** Fixed in `model/pdf_text_edit.py`: `_simple_font_can_encode` (printable Latin-1 only) routes all other text to htmlbox in `_classify_insert_path` and in protected-span replay; `_verify_rebuild_edit` / `_validate_protected_spans` compare NFKC-folded text and roll back when any requested character is missing from the page. Arabic, Hebrew, Thai, Cyrillic, `€`, combining marks and ZWJ now commit intact; emoji, CJK Ext-B and Devanagari (lossy htmlbox text layer in PyMuPDF 1.27) were refused with the page untouched -- superseded in round 11 by OD-UNI1-COMMIT (below): they commit on glyph evidence; Ext-B commits since EXTB-SUBSET (below) where a Windows Ext-B font is installed. See PITFALLS.
- [x] **OD-UNI1-COMMIT: consented rebuilds with emoji / non-BMP characters / shaped clusters commit with the htmlbox rendering (owner decision on round 10's refusal, round 11).** `_verify_rebuild_edit` and `_validate_protected_spans` forgive a requested character missing from the page text only on glyph evidence: htmlbox's own scratch render of the same markup lacks it too, draws no .notdef, the character is not a placeholder (U+FFFD / Cc / Co / Cn / Cs -- unless untouched and acknowledged in the consent, F11-UNI-1 decision C), and every `(font, glyph id)` of the scratch render is drawn on the page. Characters htmlbox can encode must still be in the page text. Covers emoji, Devanagari, Gujarati/Tamil conjuncts, Arabic lam-alef, any other script whose htmlbox ToUnicode is lossy. See PITFALLS.
- [ ] **Accepted limitation (OD-UNI1-COMMIT): text committed that way has a WRONG text layer -- copy/paste, search, screen readers and the app's own index return other characters.** PyMuPDF 1.27 htmlbox cuts non-BMP code points to 16 bits (U+1F600 -> U+1F60, U+1F44D -> U+1F44; CJK Ext-B drawn through EXTB-SUBSET too: U+20B9F -> U+20B9, U+20000 -> U+2000, a space) and maps conjunct/ligature glyphs to their glyph id read as a code point (`हिन्दी` -> `ह` U+0259 U+010F `दी`; `ક્ષત્રિય` -> `óú` + `િય`; `لا` -> U+01BE U+0006). Re-opening the editor on such a line later shows the wrong characters too (the index is rebuilt from extraction), and editing them again would commit those. A real fix needs a correct ToUnicode (or ActualText) for the inserted glyphs; candidates, none verified: (a) after the insert, rewrite the inserted font's /ToUnicode CMap from the shaping result (glyph id -> the source cluster's code points, UTF-16 surrogate pairs, one-to-many entries) -- htmlbox does not expose the cluster map, so this needs our own shaping pass (HarfBuzz / uharfbuzz, a new dependency) over the same font; (b) probably the cheapest: wrap the htmlbox insert (its XObject `Do` in the page content) in a marked-content `/Span << /ActualText <FEFF...> >> BDC ... EMC` carrying the requested text (UTF-16BE) -- probed: PyMuPDF 1.27 extraction returns U+1F600 intact through ActualText (Acrobat honours it too); open: one ActualText for a wrapped multi-line insert gives coarse per-character geometry for search highlights and selection, and the tiered engine / Tier 0 must not later patch inside such a span; (c) an upstream MuPDF fix for story/htmlbox ToUnicode (non-BMP and clusters) plus a PyMuPDF minor bump (the pin is single-minor); (d) insert through our own Type0 / Identity-H font with a complete ToUnicode (same shaping need as (a)).
- [x] **EXTB-SUBSET (owner decision C on OD-UNI1-COMMIT, implemented round 11): consented rebuilds draw CJK Ext-B (U+20000 and up) from an in-memory fontTools subset of the Windows Ext-B font.** The htmlbox chokepoint `insert_htmlbox_tracked` wraps Ext-B runs in their own span and passes the subset through an in-memory archive (`utils/cjk_ext_b_font.py`); per character SimSun-ExtB `simsunb.ttf` first (60,349 code points from U+20000, Ext-B to Ext-F), MingLiU-ExtB `mingliub.ttc` face 0 as the fallback (11 compatibility ideographs SimSun-ExtB lacks; used alone when `simsunb.ttf` is missing); both fsType 0x8 (editable embedding). Measured +2,379 bytes per saved file for 2 glyphs, +10,069 for 40 (test bounds 16 KB / 64 KB). Font missing (not Windows / not installed / unreadable): still refused, the reason now names the fonts. fontTools is a core requirement now (`requirements.txt` / `pyproject.toml` `fonttools>=4.60.2,<5`; `constraints-ci.txt` pins per interpreter because fontTools 4.66 needs Python 3.11+ while CI runs 3.10: 4.66.1 (the .venv) on 3.11+, 4.65.0 on 3.10 -- so CI exercises fontTools 4.65.0, not the .venv's 4.66.1; the subsetter was also run against 4.60.2, the floor). Text layer stays lossy (16-bit cut, accepted-limitation item above). See PITFALLS. Fixed in round 12 (S12-EXTB-PREVIEW): the editor's live CSS preview (`PreviewRenderer.render` in `view/text_editing.py`, a bare `insert_htmlbox` the view could not route through the model's chokepoint) drew an empty box for Ext-B while the committed page was right; the @font-face/archive plumbing now lives in `utils.cjk_ext_b_font.htmlbox_args_with_ext_b` (view -> utils is allowed), used by both the chokepoint and the preview, and an AST guard requires it of every `insert_htmlbox` call in `view/`, `controller/` and `utils/`. Open: (1) not driven through the GUI / a real IME (the default tiered engine previews an existing line from the plan raster, which goes through the chokepoint; the CSS preview is the add-new-text-box and legacy-engine path); (2) the font-missing refusal now reaches the user as one zh-TW sentence (ZH-REFUSALS); (3) Windows only, and not driven through the GUI / a real IME; (4) the new runtime dependency was not run through `pip-audit` locally (the CI audit job covers `requirements.txt`); (5) `_is_identityless_placeholder` treats Cn as a placeholder, so on Python 3.10 (Unicode 13.0) an Ext-B code point added later (U+2A6DE / U+2A6DF, Unicode 14) is refused although SimSun-ExtB draws it. Original options, for the record: (A) keep the refusal (now worded `no font draws some of the requested characters (.notdef glyph): U+20000`); (B) fall back to the Windows Ext-B fonts through `@font-face` (`simsunb.ttf` SimSun-ExtB or `mingliub.ttc` MingLiU-ExtB, wrapping Ext-B runs in their own span; probed: renders) -- but htmlbox embeds the whole font: +11.7 MB (SimSun-ExtB) / +17.2 MB (MingLiU-ExtB) per saved file, Windows only; (C) (B) plus in-memory subsetting of the Ext-B font before the insert (fontTools, today only a dev dependency, would become a runtime one) -- small files, more code; (D) bundle a small Ext-B subset font with the app (licence + size review). Text layer is lossy for Ext-B in every option (16-bit cut, see above).
- [x] **F13-ENV-2 (round 13): the Ext-B font lookup ignored per-user installed fonts.** `utils.cjk_ext_b_font.find_ext_b_fonts()` now searches `%WINDIR%\Fonts` and then `%LOCALAPPDATA%\Microsoft\Windows\Fonts` (system copy first, one entry per candidate), so a no-admin install satisfies the install advice and `ext_b_install_would_help()` turns False. Tests: `test_cjk_ext_b_font.py` (`test_per_user_*`). Not covered: fonts registered under `HKCU` at a custom folder; not reproduced on a real stripped Windows image.
- [x] **F13-ENV-3 (round 13): an unimportable fontTools was reported as "the installed Ext-B fonts have no glyph".** `utils.cjk_ext_b_font` now separates a broken install from a font without the glyph: `fonttools_import_error()` / `ext_b_component_missing()`, no empty coverage cached while the import fails, one ERROR log, and the new refusal `EXT_B_COMPONENT_MISSING` (zh-TW: reinstall the program). Tests: `test_cjk_ext_b_font.py`, `test_text_edit_refusal_messages.py`. PITFALLS Ext-B entry (Round 13, F13-ENV-3).
- [x] **S14-EXTB-PREVIEW-WORKER (round 14, owner decision C on F13-EXTB-PERF-1): the live preview's Ext-B font subset ran on the GUI thread.** New character sets cost 0.14-0.31 s per pause in typing. `PreviewRenderer.render(defer_ext_b=True)` (the inline editor) now reads the subset caches only (`htmlbox_args_with_ext_b(cached_only=True)`, `ExtBSubsetNotReady`), draws a transient .notdef frame on a miss (native Qt text when that frame has no other ink) and the editor's `ExtBSubsetService` (`view/ext_b_subset_worker.py`, QThread, latest request wins, stale results dropped, closed with the editor, awaited at `aboutToQuit`) fills the caches and triggers a re-render; measured GUI stall 2-3 ms. The commit path still subsets synchronously (once per Apply). Open: not driven through a real GUI session with a human typing. See PITFALLS.
- [x] **F11-UNI-1 (decided C, implemented): a consented legacy rebuild of a line carrying an UNTOUCHED glyph with no Unicode identity (U+FFFD, a C1 code from an unknown glyph name, private use such as the Symbol-font bullet U+F0B7 or U+E000) commits only when the consent dialog said that glyph will change or disappear.** Before the ask the model reports the glyphs (`_rebuild_glyph_loss` -> `UnkeepableGlyph(span_id, index, codepoint, fate)`, edited text AND replayed neighbour runs; exposed as `PDFModel.pending_rebuild_glyph_loss` only during the callback); the controller's dialog adds one zh-TW line (N 個符號無法保留，會變成其他符號或消失, counts only); Yes returns `RebuildConsent(acknowledged_glyph_loss=<report>)` and the model accepts it only on exact equality. A bare `True`, a stale or partial acknowledgement, or a placeholder the USER typed keeps refusing. Also closes a silent hole: a U+FFFD in an overlapping neighbour run passed `_validate_protected_spans` (`normalize_text` drops U+FFFD) and was redrawn as another glyph -- now refused unless acknowledged. Open: the cross-page move asks before the model runs (bare `True`), so a move of such a line still refuses; its dialog no longer tells the user to "confirm at the prompt" (F12-DLG-3: the move maps its own zh-TW sentence, `refusal_message(code, cross_page_move=True)`; owner choice still open for making such a move succeed: a second, glyph-naming ask on the source deletion, or a glyph preflight before the move's single ask); the text layer of the result carries the replacement (U+0239 / U+037D) or NUL; the refusal for typed / unacknowledged placeholders now reaches the user as one zh-TW sentence (ZH-REFUSALS). PITFALLS entry "A consented rebuild of a line with an untouched U+FFFD / PUA / C1 glyph ...".
- [x] **F12-DLG-4 (round 12): the Ext-B refusal told users to install fonts that were already installed.** `EXT_B_FONT_MISSING` (install advice) is now raised only on Windows with no candidate Ext-B font (`ext_b_install_would_help()`); an installed font lacking the glyph (Ext-G+) and non-Windows platforms get `NO_FONT_FOR_CHARACTERS`. Tests: `test_text_edit_refusal_messages.py` (`test_ext_b_*`). Not covered: a machine with only one of the two candidate fonts that the other might cover.
- [x] **S13-DLG5-DAMAGED / F12-DLG-5 (round 13, owner decision A + C, implemented): after `ROLLBACK_FAILED` the session is latched damaged and can no longer be saved over its own file.** `DocumentSession.damaged` (set by `mark_session_damaged` at both `ROLLBACK_FAILED` raise sites, the snapshot rollbacks of `delete_pages` / `move_page` / `insert_pages_from_file` / batch delete, and the save-hook protected-page rollback failures); `save_as` raises `DamagedSessionSaveError` for the session's own file and for every file it was bound to when latched (F14-DMG-1, item below); Save As to a new file works; the `ROLLBACK_FAILED` sentence says to close the tab (not saving) and reopen. Tests: `test_text_edit_refusal_messages.py` (`test_damaged_session_*`), `test_text_commit_maintenance.py`. Not covered: a damaged session that is otherwise clean is not dirty, so closing its tab does not prompt (intended: the sentence says to close without saving); the latch is never cleared for the session (a Save As keeps it, so later Ctrl+S on the new file is refused too -- say so if the owner wants it lifted after a Save As).
- [x] **F14-DMG-1 (round 14, implemented): a damaged session stopped protecting its original after one Save As.** A second Save As (or export / merge / optimize copy / a detached tab's Save As) back onto the opened-from file overwrote the only good copy, because the gate read the session's current paths, which a Save As rebinds. `mark_session_damaged` now freezes the bound files into `DocumentSession.damaged_protected_paths`; `PDFModel.damaged_protected_paths(sid)` is the one source for the Save As gate, `save_external_document`, `copy_lost_session_recovery`, the optimize snapshot and the tab-transfer payload. See PITFALLS F14-DMG-1. Not covered: another (clean) tab may still Save As over the original once the damaged tab left it; files bound before the latch are not protected.
- [x] **F13-MOVE-1a (round 13, implemented): the cross-page move's message and damaged latch follow its own whole-document restore.** `move_text_across_pages` tracks `document_restored`; a successful restore turns the `ROLLBACK_FAILED` sentence into the "page restored" one and lifts the model latch it caused (`PDFModel.clear_session_damaged`, only when the session was not damaged before the move); a failed restore shows the do-not-save sentence and latches the session. PITFALLS entry F13-MOVE-1a.
- [x] **F13-MOVE-1b (round 13, verified, no code change): a cross-page move whose whole-document restore also fails.** Already covered by the F13-MOVE-1a latch: the dialog is the do-not-save sentence (not "try again"), the session is damaged so no in-place write can persist the lost source text; no undo entry / dirty mark is intended (see PITFALLS F13-MOVE-1a, Pinned). Regression tests `test_a_lost_source_with_a_failed_restore_*`. Open separately: retry of the same move after the source was lost deletes the neighbouring block (positional span-id fast path).
- [x] **ZH-REFUSALS (owner decision "Refusal UI", round 11, implemented): every refused text edit reaches the user as ONE plain Traditional Chinese sentence per refusal reason, never the exception's English technical text.** The Model raises `TextEditRefused(reason: TextEditRefusal, detail)` (`model/text_edit_refusal.py`, Qt-free, a `RuntimeError` subclass; `_RebuildRolledBack` derives from it) with a stable code: `redaction_left_source` (vertical / unredactable text, F10-UNI-3), `text_does_not_fit`, `characters_lost`, `unidentifiable_glyphs_not_acknowledged` (F11-UNI-1, also for a replayed neighbour), `ext_b_font_missing`, `no_font_for_characters`, `glyphs_not_drawn`, `target_not_present`, `protected_span_changed`, `verification_failed`, `rollback_failed`, `edit_failed` (any other failure inside the edit, page rolled back). `_lossy_text_layer_problem` returns a `str` subclass carrying the code. `controller/text_edit_refusals.py` maps code -> sentence (no Latin letters, says what happened and what to do, never quotes document content); an unknown code or an uncoded exception gets `GENERIC_REFUSAL_MESSAGE` and the technical detail goes to the log only (`log_edit_failure`). Covered paths: `edit_text`, `move_text_across_pages` (its own aborts are `UserFacingEditError` with a plain sentence already) and `add_textbox`. Open: (1) not driven through the real GUI by a human; (2) fixed in round 12 (S12-REDO-REFUSAL): undo / redo are now an exception boundary (`_report_history_step_failure`: log, one modal zh-TW dialog, stacks untouched; PITFALLS "A coded refusal from a redo-time re-run escaped the Qt slot"); (3) `EditTextResult.REJECTED` / `FALLBACK_DECLINED` notices were already zh-TW and are unchanged; (4) the sentences are static text, so a new `TextEditRefusal` member without a sentence is caught only by `test_every_refusal_code_has_a_plain_zh_tw_sentence`; (5) other `show_error(f"...{e}")` sites outside the text-edit path (open, insert pages, watermark, annotation, snapshot) still show English exception text. PITFALLS entry "A refused text edit reached the user as the English technical modal (ZH-REFUSALS)".
- [ ] **F11-UNI-1 option D (not started): keep an untouched identity-less glyph through a rebuild by replaying the original run around the edit** (copy the source show / glyph codes of the untouched part instead of re-typesetting it through htmlbox, so U+FFFD / PUA / C1 glyphs stay exactly as drawn and the decision-C dialog line is no longer needed for them). Larger engine work across the rebuild insert and verification; picking it up needs a `plans/` file (goal, modules, steps, decisions) first.
- [ ] **F10-UNI-1 siblings, not fixed (no consent/SUCCESS flow): `insert_text(helv)` still writes `·` for non-CJK, non-Latin-1 text in OCR `apply_ocr_spans` (`_pick_ocr_font`), watermark text (`resolve_watermark_font`) and tiny-canvas `_insert_tiny_plain_text`.** htmlbox cannot do the invisible `render_mode=3` OCR layer and no built-in `insert_text` font covers Arabic/Thai (`china-ts` drops them), so each needs its own design (bundled Unicode font file or htmlbox with opacity).
- [x] **F10-UNI-3: a consented rebuild of vertical (Identity-V / WMode 1) text left the original column and overlaid a rotated, space-padded copy, reported SUCCESS (round 10).** MuPDF redacts WMode 1 glyphs one em above their extracted boxes, so the rebuild's redaction missed the source and `_verify_rebuild_edit` never checked removal. `_apply_redact_insert_body` now refuses (`_RebuildRolledBack`, page rolled back) when any glyph in the redact rect survives `apply_redactions`; the push-down skips vertical neighbours. Vertical Identity-V text therefore cannot be edited by the legacy rebuild at all (tiered refuses it too). See PITFALLS. Open (owner): a real vertical redaction (rect shifted by the font's vertical origin from `/DW2` / `/W2`) would make such edits possible; not attempted. Also noted: `_redact_and_restore_textbox_region` (`pdf_object_ops.py`) has the same MuPDF limit for vertical page text under a textbox, but replays nothing so it cannot duplicate.
- [x] **F10-UNI-2: the block-level `NO_CHANGE` gate in `_resolve_edit_target` dropped case-only, curly-quote, ZWSP and spacing edits that the tiered engine commits (round 10).** The gate now uses `is_unchanged_text` (exact after ligature / U+FFFD extraction artifacts) instead of `normalize_text`. See PITFALLS. Open (owner): the view's change detector `_normalize_for_edit_compare` (NFKC + whitespace collapse) still discards fullwidth/CJK-punctuation-to-ASCII and NBSP edits before a request exists; narrowing it is a product choice (accidental-whitespace tolerance vs. NFKC-extraction divergence).
- [ ] **Owner real-app re-acceptance (round 7).** On a copy of `ecc-dwg.pdf`: (1) S17a: grip-move an existing
  text, no second 備 at the old spot, also after typing 點 first, at 100 % and 214 %; include a run that touches a
  table rule (patch margin); (2) plan-mode IME shows no chip, only the strip preedit and the badge; (3) a grip
  move on a 90/270 `/Rotate` page lands where it was dropped and the apply uses the new place; (4) the
  committed move and Escape both remove the patch; (5) a short run next to another run on the same baseline: the
  neighbour stays visible while the short one is away; (6) on a hatched or picture background the source text
  stays visible beside the moved box (no flat block), and drags back to the exact spot leave Apply enabled;
  (7) Ctrl+S or a zoom change in the middle of a grip drag applies the move where the box is. The offscreen S17a
  manual run is a gate-step item, not a substitute for the owner's run.
- [ ] **Intentionally changed existing tests (round 7, need owner/main-session sign-off):**
  `test_text_commit_editor_mouse_gestures.py::test_move_grip_drag_moves_the_editor` (rewritten: 4 rotations, both
  axes, the 90 degree special case and the rotation guards removed; fixture refactor `_gui_session` /
  `_write_page(gray, pages)`; `_open_ecc_run_at` merged into `_open_ecc_run`);
  `test_text_editing_gui_regressions.py::test_finalize_text_edit_removes_mask_item` (also seeds and asserts the
  origin patch);
  `test_text_commit_plan_preview_no_css.py`: module docstring,
  `test_pending_paints_frozen_frame_badge_and_chip` -> `..._frame_and_badge`,
  `test_verified_raster_paints_without_badge_then_stays_as_last_frame` (chip-text assert removed),
  `test_composing_chip_paints_the_elided_parts_...` (now plan_mode False with `_regenerate_preview()` and a
  `_mutated_preview_is_valid` assert), `test_refused_preview_paints_the_typed_text_chip_and_a_refusal_badge` ->
  `test_refused_preview_paints_the_refusal_badge_over_the_base`;
  `test_text_commit_finalize_policy.py::test_a_preedit_is_visible_in_the_editor_paint` (chip-text assert replaced
  by the live-strip `preedit_area()` check);
  `test_text_commit_real_ime_round4.py` (two names/docstrings, one rename to `..._repaints_the_refusal_badge`);
  `test_text_commit_live_text_strip.py` (one comment). Round 1 review fixes changed more on purpose:
  mouse_gestures `test_cross_page_grip_move_keeps_the_origin_page_covered` and
  `test_grip_move_leaves_no_source_glyph_or_sliver_on_the_owner_run[100%|214%]` now expect the span-based aligned
  cover via `_expected_origin_cover(view)` instead of widget rect + margin; `test_text_editing_gui_regressions.py`
  fake views set `_editing_origin_span_scene_rect` (patch expected = span + margin) and gained a "no span -> no
  patch" case; the mouse_gestures fixtures gained `gui_neighbour` and `gui_stripes`, and `_write_page` the
  `neighbour` / `stripes` options. Review S5/S6 added `test_grip_moves_an_add_text_box_on_a_rotated_page_by_the_drag`
  and merged `_open_ecc_run_at`. `test_text_commit_editor_mouse_gestures.py`,
  `test_text_commit_live_text_strip.py` and `test_text_commit_real_ime_round4.py` are untracked round 6 files
  with no git baseline: the review compared test names against the round 6 gate log, not bodies.

## 2026-10-07 True-text UI part 5 round 6 (live strip, in-box caret, save size) -- found, not fixed

Fixed in round 6 (`plans/true-text-ui-part5.md` section 13, `docs/ARCHITECTURE.md` sections 2.1 and 10.2,
`docs/PITFALLS.md`): no caret/selection/legible text in plan-preview mode (live text strip), a click with jitter
inside the open editor moving the box and refusing unchanged text (in-box mouse is caret/selection, explicit
move grip), and a 222 KB file saved as 5.9 MB after rebuild + Ctrl+Z (save-time pruning, font compaction).

- [ ] **Owner real-app re-acceptance (round 6), real Windows IME, on a copy of `ecc-dwg.pdf`.** Offscreen tests
  cannot prove: (1) the candidate window opens at the strip caret and the preedit looks right; (2) pressing in
  the box or the strip WHILE COMPOSING commits the composition at the OLD caret, not the clicked one (Qt does not
  promise the `commitString` event arrives before `commit()`/`reset()` returns; the helper is
  `commit_ime_composition` in `view/text_live_strip.py`, tests only use a spy input method); (3) a Shift-click
  while composing followed by the next IME keystroke does not delete the new selection (`QWidgetTextControl`
  removes the selection on the next IME input); (4) the hover cursor over the open box is an I-beam (offscreen
  Qt shows one by itself, the Windows window showed a hand); (5) the saved file after rebuild + Ctrl+Z + Ctrl+S is
  about the original size.
  2026-10-26 owner run: (1) passed (candidate window at the box, preedit legible); (2)-(5) were not exercised in that run (the page click while composing was cancelled by the editor, so the old-caret commit case is still unproven).
- [ ] **P4: rebuilt text is re-editable only as fragments.** Hover/click on rebuilt text highlights a fragment
  (e.g. 「I…」). The rebuilt line is one `TJ` inside a nested form XObject (`/fzFrm0` -> `/fullpage`, xref 119 ->
  118 on the `ecc-dwg.pdf` copy); the block parser splits it into 4 runs at latin/CJK kind changes
  (`model/text_block_parsing.py:448-451`) and `SourceRunResolver.page_groups` finds no group for it (71 groups
  against 74). Making it one run is resolver scope (form-XObject source runs). Every further edit of rebuilt text
  therefore tends to need another rebuild and another font copy.
- [ ] **Subset the rebuild font (`kaiu.ttf` and the other whole `@font-face` fonts).** The precondition this item waited
  for is RESOLVED: `fontTools` is a pinned core requirement since EXTB-SUBSET (round 11; `requirements.txt`,
  `pyproject.toml`, `constraints-ci.txt`), which subsets only the CJK Ext-B fonts. Subsetting the other rebuild fonts
  is still not started and needs its own decision. Round 6 is compress-only (`model/font_stream_compaction.py`): a kept `kaiu.ttf` rebuild still adds about
  2.9 MB compressed per surviving copy (the CMap about 96 KB). `doc.subset_fonts()` is NOT an option: it rewrote
  original fonts 8 and 67 (40,726 -> 214,442 and 46,798 -> 177,698 bytes). Subsetting also removes glyphs later
  true-text edits of rebuilt text may need.
- [x] **Retire the plan-mode chip (owner decision).** Done round 7: plan mode paints only the badge; the
  typed text and the preedit are in the live strip. The composing chip stays for non-plan editors (add_text,
  legacy), where it is the only preedit echo (open item in the round 7 section at the top).
- [ ] **Raster-aligned in-box caret.** Needs per-glyph geometry of the NEW text (`PlanPreviewRenderer.render`
  holds `interpret_page(page)`; `replay/glyph_boxes.py:predict_glyphs`) carried in `PlanPreviewResult` through
  `_consume_plan_preview` to the view (DTO change across Model/Controller/View). Pending or refused text has no
  raster at all, so the strip stays for those states.
- [ ] **Known `garbage=0` sites left on purpose:** `capture_worker_snapshot_bytes` (every search/OCR/print
  snapshot; `garbage=1` was not measured per render revision), `ToolManager.build_print_snapshot` (temporary print
  input) and `save_external_document`; whole-document undo snapshots (`tobytes(garbage=0)`, memory only).
- [ ] **Orphans persisted by an earlier incremental save stay in the file** (they sit below
  `persisted_xref_length`, so the 64 KiB fallback does not see them) until a full or secure save. A modified
  base-file object that became unreachable is still written by a true incremental save (never nulled live: PyMuPDF
  `InsertedImages` cache, see PITFALLS).
- [x] **Rotated-page box move.** Done round 7: `_proxy_corner_offset` / `_proxy_visual_extent` /
  `_quarter_turn_proxy_layout` (the rotated proxy `pos` is a corner of the box; the clamp, `editing_rect` and
  the page-resolve centre now use it); `test_move_grip_drag_moves_the_editor` runs on 0/90/180/270 and both
  axes. Residual: a cross-page move onto a page with a different `/Rotate` (round 7 section at the top).
- [ ] **Dead code: the first-click pending-drag branch** (`_pending_text_info` is only ever set to None; the
  old pending-release caret branch in `_mouse_release` is unreachable). Kept because
  `test_text_edit_manager_foundation.py` resets the attribute; delete both together. The mouse-move twin
  (`_drag_pending` in `PDFView._mouse_move`, also dead) is still there; round 7 only made it call the fixed
  clamp and page-resolve helpers.
- [ ] **Perf nit:** each keystroke triggers 2-3 `inputMethod().update()` calls (strip `anchor_changed` per
  refresh plus `_position_text_action_bar`) and `setCursor` runs on every mouse move; coalesce to one call per
  event-loop turn if profiling shows it.
- [ ] **`_ACTIVE_SCOPES` in `model/font_stream_compaction.py` is keyed by `id(doc)`.** A document closed inside
  an open scope whose id is reused would look scoped; no current path does this. Use a `WeakKeyDictionary` if
  `fitz.Document` supports weakrefs.
- [ ] **Intentionally changed existing tests (round 6, need owner/main-session sign-off):**
  `test_small_drag_can_activate_editor_move` (replaced by two tests),
  `test_multi_tab_plan.py::test_19ac_inline_existing_text_cross_page_move_roundtrips_via_document_undo_redo`
  (now drags the move grip), and the probe points of `test_hover_inside_open_editor_shows_ibeam` /
  `test_a_press_on_the_bar_or_outside_the_box_keeps_the_composition` (taller two-row bar).
- [ ] **Not measured:** the first-click delay (about 5 s busy cursor on the first click after opening); out of
  scope of round 6.
- [ ] **Test scripts that pytest does not collect** (`test_unified_undo.py`, `test_drag_move.py`) fail in
  steps unrelated to round 6 when run as scripts (tiered engine refuses without `allow_rebuild`; model-level
  move A/B); reproduced on a HEAD tree. Decide whether to port them to pytest or delete them.
- [ ] **`.venv` lacks `setuptools`**, so `test_security_packaging::test_built_wheel_and_sdist_exclude_dev_trees`
  fails with `ModuleNotFoundError` (environment, not code; CI installs it from `constraints-ci.txt`).
- [ ] **`mypy model/ utils/` is still blocked locally** by the machine's application-control policy; round 6
  used the pure-python mypy substitute (58 files, no issues). CI must confirm the real command.

## 2026-10-07 Page-snapshot restore (part 5 round 5) -- found, not fixed

Fixed: page snapshots are page-object-graph snapshots restored in place by xref (`model/page_snapshot.py`,
`docs/ARCHITECTURE.md`, `docs/PITFALLS.md`); undo of a rebuild keeps the page's layer bindings. Still open:

- [ ] **Remap page-graph snapshots across a renumbering save instead of refusing.** After a secure
  (`garbage >= 2`) serialization of the live document (`xref_epoch` bumped), undo/redo of a rebuild or an
  added textbox is refused with zero mutation. A parallel graph walk at save time could remap the snapshot's
  xrefs so the history survives the save. Printing no longer triggers this (DS-1: the secure print prune runs on a clone);
  only saves do.
- [x] **F2 in text-edit mode with a kept editor was silent** -- fixed (round 5):
  `TextEditManager.notify_same_mode_reentry` (`docs/ARCHITECTURE.md` section 10.2, `docs/PITFALLS.md`).
  Still open: the same-mode `set_mode` branch still skips `sig_mode_changed` (item below).
- [ ] **Owner re-acceptance (round 5), real app.** On a copy of `ecc-dwg.pdf`: rebuild a missing glyph, undo,
  then reorder glyphs already present: it must commit (no 「圖層結構不支援原位修改」); F2 with an un-applied
  input must toast. Offscreen tests prove the model and the notice, not the real IME.
- [ ] **Epoch bump only after a successful serialization** (`_note_live_doc_serialized`). A `garbage >= 2`
  save that renumbers the live doc and then raises would leave the epoch stale; restore gates (page xref,
  `xref_length`, `/Parent`, stream type) are the only backstop. Low probability.
- [ ] **Epoch is bumped for every secure save even when `garbage=4` renumbered nothing**, so some
  rebuild/textbox undo refusals after a secure save are unnecessary (covered by the remap item above).
- [ ] **Files saved earlier by the owner after a rebuild undo/redo or a failed legacy edit keep the damage**
  of the old `insert_pdf` restore (lost `/VP`, `/StructParents`, struct `/Pg`, TOC destinations, Popups,
  orphan OCG copies in `garbage=0` saves). Not repairable retroactively; use the original file.
- [ ] **Unverified on real corpus files:** forced rollback of a failing legacy edit, rotated pages through
  rebuild/textbox undo/redo, pages sharing an indirect `/Resources` dict (an in-place restore reverts
  shared objects changed outside history after capture).
- [ ] **`mypy model/ utils/` could not run locally in round 5** (venv mypy native module blocked by the
  machine's application-control policy: "DLL load failed while importing base64"). A pure-python mypy 1.17.1
  substitute passed (56 files); CI must confirm the real command.
- [ ] **`render_page_pixmap` overlay path still calls `insert_pdf` on the live doc** (`model/tools/manager.py`),
  which rewrites the live annotations' `/P` order (key value intact). Pre-existing, out of scope of the
  snapshot fix.

## 2026-10-06 True-text UI part 5 round 4 -- found, not fixed

Fixed in round 4 (see `plans/true-text-ui-part5.md` section 11, `docs/ARCHITECTURE.md` section 10.2,
`docs/PITFALLS.md`): refused preview painted as the frozen original, Apply/Cancel/reason/rebuild moved from
the right sidebar to the inline action bar, same-mode `set_mode` finalizing `MODE_SWITCH`, missing
click-away/Escape/composing notices, the bar's stale position after a re-centring resize. What is still open:

- [x] **Owner real-IME re-acceptance (round 4).** On a real Windows input method (新注音) on a copy of
  `ecc-dwg.pdf`: (1) reorder glyphs already present (標新設 -> 設新標): badge-free verified frame, the strip shows the text, Apply enabled in the bar,
  commit; (2) type a missing glyph: `無法套用` badge, the bar shows the reason and `改用重建文字…`;
  (3) F2 in text-edit mode keeps the input; (4) a mouse press on the bar or the page while composing does
  not reset the composition (offscreen has no platform input context: only "no focusChanged / no
  finalize" is proven); (5) the OS candidate window does not hide the bar in a way that blocks use.
  ACCEPTED 2026-10-26 by the owner on a copy of `ecc-dwg.pdf` with 新注音 (screenshots kept outside the repo): (1) 標新設 -> 設新標 in run mode: badge-free frame, Apply enabled, COMMITTED, same font/size; (2) a glyph outside the subset: `無法套用` badge, bar shows `原字型沒有這個字` + `改用重建文字…`, Apply disabled; (3) F2 kept the input with the kept-editor toast; (4) a click while composing cancelled the click and kept the composition (`組字中` badge + toast); after the composition was committed a click was ignored with the toast; (5) the candidate window opened above the box and left the bar usable; Esc closed only the candidate window, the editor stayed; Ctrl+S persisted (1) and the reopened file shows it. Follow-ups: CLOSE-PROMPT-1 (top of this file) and the two older owed items below.
- [x] **R4-5 CLOSED 2026-10-26 (owner: the `無法套用` badge appears within a fraction of a second on the real machine).** Original item: commit-to-refusal latency (about 8 s in the owner's recording) is attributed to the missing
  repaint and guarded by `test_a_slow_refusal_is_repainted_with_the_refusal_badge`.** If the owner still
  sees more than 1 s after round 4, measure `PlanPreviewRenderer.render` against `PageRenderCoordinator`
  GIL contention at 161 % zoom on a dense DWG page. `open_preview_session` -> `_live_keep_round_trip`
  runs `tobytes()` on the main thread (15 ms on `ecc-dwg.pdf`, grows with document size; may be seconds
  on `hvac-dwg.pdf`): measure and consider moving it off the main thread.
- [ ] **No direct keyboard shortcut for Apply / rebuild consent.** Round 7 / KBD-1 restored the HEAD
  path: the bar's buttons are `Qt.TabFocus` and chained after the property card (Ctrl+Alt+R twice when the
  sidebar is open, Tab to the button, Space). A one-key shortcut (Ctrl+Enter or similar, which would need
  the focus-preserving path) and a keyboard way to move the editor box (the grip is mouse-only) are still
  the owner's call.
- [ ] **Wheel events over the action bar are swallowed** (`WA_NoMousePropagation`); the page does not scroll
  while the pointer is on the bar. Accepted for now.
- [ ] **De-duplicated kept notices can leave a click-away silent.** The key is `(text, preedit)`: after a
  Ctrl+S / F5 / zoom notice (or a pending-preview notice) on the same text, a later click-away toasts
  nothing; the bar label and the `無法套用` badge carry the reason. Right-click on the page with a kept
  editor now shows the `FOCUS_OUTSIDE` notice (the scene clears its focus item on a right press); on a real
  desktop the context menu may already be open (popup suppression) -- unverified.
- [ ] **Cancel during an IME composition discards without a toast, and a bar Apply click while composing
  gives no notice** (Apply is disabled; the composing notice exists only for keep reasons). Intentional
  for Cancel; reconsider for Apply.
- [ ] **Opening or switching to another document with a refused editor discards it with the generic
  "not applied" toast** (`SESSION_SWITCH` close-always, predates round 4). Applies to a SUCCESSFUL open or
  switch only: a failed or cancelled open no longer touches the editor or OCR (F11-OPEN-4).
- [ ] **`plan_preview_badge_text()` returns `預覽更新中` even when a verified token exists** (nothing is
  painted then). Only a caller that reads the accessor without checking pending/refused is misled.
- [ ] **The `無法套用` badge is clipped in narrow editors.** On `ecc-dwg.pdf` at 100 % the editor is about
  80 px wide: the badge is an orange sliver at the right edge and, with the chip retired in plan mode (round 7),
  the only in-box signal. The strip and the bar's reason label are the readable signals; the overlay needs
  overflow handling (badge first, or outside the box).
- [ ] **`raise_()` on the bar only on hidden -> shown**: when the bar re-shows while a toast is alive it
  stacks above the toast (cosmetic; toasts sit bottom-centre).
- [ ] **`RuntimeWarning` on `sig_scale_changed` disconnect in `set_mode`** (`view/pdf_view.py`) in
  `test_text_commit_degrade_visibility.py::test_real_set_mode_toast_gating_never_fires_for_a_declined_fallback`
  (the fake-editor setups now run the real edit_text -> browse body). Not investigated; may predate round 4.
- [ ] **Same-mode `set_mode` re-entry skips `sig_mode_changed`.** Today `PDFController._update_mode` only
  stores the mode; a future side effect hooked to that signal on re-entry would be skipped.

## 2026-10-06 True-text UI part 5 -- pre-existing defects found, not fixed

Found while closing part 5 (branch `feat/true-text-edge-cases`); none was caused by
part 5 and none is fixed here. Log: `plans/true-text-ui-part5.md` section 10 and the
mother plan section 6. Line numbers are as of the part-5 working tree.

- [x] **`delete_pages` never remapped or pruned `pending_edits` / `fidelity_protected_pages`** (fixed with F17-COH-3, round 17:
  `PDFModel._pages_restructured` moves both with their pages for delete / move / insert / merge; undo restores them from the
  `MaintenanceBook`; tests in `test_text_commit_maintenance.py`, `test_delete_pages_moves_protection_and_pending_entries_with_their_pages`
  and the five after it). Original report:
  (`model/pdf_model.py` ~1390-1480; `pending_before` is only restored on an exception, ~1444/1473).
  Protection can land on the wrong page index after a delete, and a later save can run
  `clean_contents` on the page that is truly protected. Repro: Tier 0 edit on page 3 (protected),
  delete page 1, save: protection still names index 2 (now the old page 4) and the edited page
  is rewritten.
- [x] **`SnapshotCommand.undo` restored document bytes but not `fidelity_protected_pages` /
  `pending_edits`** -- fixed in the part 5 final review (2026-10-06): `MaintenanceBook` +
  `DocSnapshot` (`model/edit_commands.py`), captured at the one chokepoint
  `PDFModel._capture_doc_snapshot` and restored by `SnapshotCommand` on undo AND redo;
  `AddTextboxCommand` and `EditTextCommand` (HIST-1: a consented rebuild's entry outlived its
  undo and later made a save clean a Tier 0 page) use the same class. Tests:
  `test_text_commit_maintenance.py` (`test_undoing_an_object_op_...`, `test_redoing_an_object_op_...`),
  `test_text_commit_pending_maintenance_retired.py` (`..._consented_rebuild_own_its_cleanup_entry`,
  `test_tier0_redo_survives_a_save_after_...`). The structural commands (`delete_pages`, `move_page`, inserts, merge) now
  remap the page-indexed bookkeeping (first item above, F17-COH-3), so a restored book is consistent with the indices the
  operation left.
  R5-BOOK-1 (same class, fixed): a FAILED legacy `edit_text` (overflow, verify, unexpected error) now restores
  the page-scoped book with the bytes (`pdf_text_edit._rollback_rebuild_page`).
  SWEEP-A1 (same class, fixed at the chokepoint): `PDFModel._restore_doc_from_snapshot` now restores the
  `DocSnapshot`'s book with the bytes, so a failed `delete_objects_atomic` batch (and the `delete_pages` /
  `move_page` / cross-page-move rollbacks) no longer leaves a verified Tier 0 page unprotected and pending.
  Tests: `test_text_commit_maintenance.py` (`test_failed_batch_delete_...`, `test_restore_doc_from_snapshot_...`).
- [x] **Watermark saved over the open file stacks another copy per save** (fixed with M9-2: `_install_stage_over_open_file(keep_live_content=True)` rebinds the session to the unbaked live recovery copy, so the live handle never reads the baked target; tests `test_text_commit_persistence.py::test_watermark_save_over_the_open_file_does_not_stack_copies`; the save-and-REOPEN variant is F17-COH-2, fixed in round 17). Original report:
  (`model/tools/watermark_tool.py:94 on_session_saved`; `_watermarks_by_session` is not cleared after
  the live handle is swapped to the file that already has the watermark baked in). Repro: add a
  `DRAFT` watermark, Ctrl+S three times: the page text contains `DRAFT` 1, 2, 3 times.
- [ ] **`clean_contents` on the optimize copy ignores `fidelity_protected_pages`**
  (`model/pdf_optimizer.py:547`). Protected pages are rewritten in the optimized output. The copy is
  disposable and the option is user-chosen, so this is not a live-document leak; decide whether
  "optimize" should skip protected pages or say so.
- [ ] **Ctrl+S with a plan token the Controller then refuses says "document unchanged" while the save
  proceeds** (`controller/pdf_controller.py` ~2467-2512 refusal toast, texts ending
  "(文件未變更)"; `view/text_editing.py` `_kept_notice` ~2682-2711 returns `None` for
  `SAVE_SHORTCUT` when `emitted=True`, so the Controller's toast is the only word). Repro: open an
  editor, get a verified token, make the Controller refuse the commit (e.g. strict mode or a stale
  source), press Ctrl+S: toast "...未套用（文件未變更）", then the modal "儲存完成".
- [x] **`EditTextCommand` relocation trigger was broader than the bug it fixes** -- fixed in the
  part 5 final review (2026-10-06): the command stores a renumbering-invariant page fingerprint at
  commit (`renumber_invariant_page_fingerprint`, `model/text_commit/inspect.py`) and relocates only when
  the current page still matches it, so a foreign font/ExtGState/annotation/`/Rotate`/box/stream change
  (OCR included) is `STALE_UNDO` with zero mutation again; relocation is also exception-safe. Tests:
  `test_text_commit_persistence.py` (`test_undo_refuses_when_anything_but_a_renumbering_changed_the_page`,
  `test_a_raising_relocation_helper_...`). Known limits of the invariant (by design, see
  `docs/ARCHITECTURE.md` section 10.2): image pixels, page thumbnails/metadata/`/PieceInfo` and the
  page tree above the page are not covered, and a page whose object graph cannot be parsed within budget
  gets no invariant (relocation is then refused, undo after a renumbering save stays `STALE_UNDO`).
- [ ] **Tighten the save-guard clone check** (`model/tools/manager.py:128 _ProtectedPageGuard.violations_in_clone`;
  round-3 N4/N5). Today a returned clone only has to keep each original content stream as an ORDERED
  SUBSEQUENCE of `/Contents`, so a hook could prepend a `cm` that scales protected text; fonts and
  ExtGState are not guarded at all. Target: "originals contiguous, additions only as balanced `q`/`Q`
  overlays that cannot transform them". Checked how the only producer, `WatermarkTool`
  (`model/tools/watermark_rendering.py:66 page.insert_text`, clone from `watermark_tool.py:125`), places
  its streams: PyMuPDF wraps the page as `[ "q" stream, original(s), "Q" stream, "q ... Q" overlay ]`
  (measured on a Tier 0 fixture: `[5] -> [8, 5, 9, 10]`), so the originals stay contiguous but there IS an
  addition BEFORE them. A rule that forbids any prefix stream would break the watermark; the rule must
  accept a prefix that is exactly one unbalanced `q`, matched by a leading `Q` in the suffix, and an
  overlay whose `q`/`Q` nest to zero with no `cm`/`Do`/`gs` that reach back out. Needs a content-stream
  tokenizer pass over the added streams (the existing one has no inline-image mode, see the item below).
- [ ] **Plain-undo page gate hashes annotations by xref + rect only** (`model/text_commit/inspect.py:601-606`
  in `page_fingerprint`, entries from `_annotation_entries` :518; round-3 N6). A change to an annotation's
  `/AP /N` stream (or any other annotation key) is therefore admitted on the plain, non-relocated undo,
  while the relocation path (`renumber_invariant_page_fingerprint`) refuses it. Make the plain gate fold
  the annotation's content, as the invariant fingerprint does.
- [ ] **Defect 12: `test-complexed-layout.pdf` first span edit ends `no_source_match`.** A Tier 0
  binding gap (Type3 decode leg, a run split across shows, `NO_MATCH` reason honesty), to be handled
  under the T16-4X glyph-coverage umbrella. Repro: open `test_files/test-complexed-layout.pdf` (a
  copy), edit one character of the first span, Apply: refused `no_source_match`. No `case_id` is
  added for it.
- [ ] **Owner real-IME acceptance still owed** (first attempt failed on 2026-10-06 and led to round 4,
  see the round 4 section at the top). On `ecc-dwg.pdf` with a real input method: candidate
  window position, composition commit/cancel on focus change, Escape. Off-screen tests cover the
  logic and the paint of the badge and the non-plan preedit chip only (`docs/ARCHITECTURE.md` section 10.2).

## 2026-09-22 專案真文字保真 skill

- [x] 建立 `.agents/skills/pdf-text-fidelity/SKILL.md` 與共用入口；完成格式、連結、Git 收錄、Ruff 與六種獨立情境演練。區分腳本、engine、UI 證據，以編輯前後字型／大小／位置一致為完成標準；此項不代表正式引擎修正完成。

## 2026-09-21 三份 CAD 圖面擴充實證

- [x] 完成 12 處 PyMuPDF 修改：ECC 新增標楷體 4 處；CHB 與[AIRPORT_CODE]共 8 處原向量字形複用。MuPDF / Poppler 非目標區域像素差異均為 0；見 `docs/experiments/2026-09-21-three-cad-font-edits.md`。
- [ ] **延後：向量／轉曲文字。** 另行規劃字形分組、字義辨識、donor 覆蓋率與跨串流路徑安全性；無 font/text 的 CAD 圖面不得算入真文字引擎的成功條件，也不得在本輪正式程式修改中處理。

## 2026-09-22 真文字高保真提交（進行中）

- [ ] 由 gpt-5.6-sol 先建立真文字驗收測試：HVAC 10 筆與 ECC 4 筆嵌入 Type0 文字，驗證原字型/CID、完整文字狀態、局部影像及零非目標差異；向量案例排除。
- [ ] 交由 Claude Code 依 `plans/2026-09-22-claude-code-true-text-implementation.md` 修正式引擎與 UI，讓上述真文字測試通過；不得以自動 legacy 重建／系統字型 fallback 冒充成功。

## 2026-09-21 HVAC 字型實證

- [x] 以 PyMuPDF 完成 Bb 圖說 10 處原資源文字修改、存檔重開、逐處影像與非目標區域驗證；見 `docs/experiments/2026-09-21-hvac-font-edits.md` 和 `scripts/experiment_hvac_font_edits.py`。
- [ ] 後續產品修正以該 10 筆為樣本，獨立追查 `mc_malformed_pairing`、scratch fingerprint `verification_failed`、`trm_reflected` 與 UI 實際 fallback；此次只有實驗，尚未修正正式編輯器。

## Acrobat-parity text commit engine — harness prep (plans/2026-07-18-acrobat-stable-text-commit-engine-v2.md)

Before any engine code (Phase A onward), the environment/CI gaps that would let
the fidelity checks (byte-identical stream patching, render-diff) pass/fail
inconsistently by machine needed closing first. Scoped and landed one slice at
a time (not batched) per the milestone-1 lesson on PR size.

- [x] **PyMuPDF pinned to a single minor (`>=1.27,<1.28`), not a floor.** Was
  `>=1.23`, which let `.venv` (1.27.1) and a bare system-Python run (observed
  1.25.5) silently diverge in stream serialization / `extract_font` behavior —
  exactly the signal a byte-identical fidelity check needs to trust.
  `test_scripts/test_environment_pins.py` fails loudly on skew. `docs/PITFALLS.md`
  "PyMuPDF version skew masks runtime-only bugs".
- [x] **Device-identity pre-commit guard.** `scripts/hooks/pre_commit_device_guard.py`
  scans added diff lines for local machine paths/hostnames/MAC addresses (the
  class of leak from the 2026-07-15 history-rewrite incident); installed via
  `scripts/hooks/install_git_hooks.py` (opt-in per clone) and enforced
  unconditionally by the new `device-guard` CI job. Relevant because
  Phase A's telemetry (§4.7) will start dumping stream hashes / font metadata /
  local paths on failure — this closes the leak path before that lands.
- [x] **Synthetic fidelity corpus generator** (`scripts/build_fidelity_corpus.py`) —
  generates 10 synthetic PDFs on the fly (no checked-in binaries; `*.pdf` stays
  gitignored) covering each decision-gate case: base-14 unembedded Type1,
  embedded CIDFont/Type0 (extractable + reloadable), CJK Identity-H, TJ
  kerning arrays, rotated text (G4), Form XObject (G2), `/Differences`
  encoding (F3), Type3 font (F1), multi-style runs (T0a), neighbor proximity.
  Test: `test_scripts/test_build_fidelity_corpus.py` (19 structural assertions).
  No longer blocks Phase A.
- [x] **ε calibration for V1d render-diff** (open question 4 in the plan) —
  DONE 2026-07-18.  Script: `scripts/calibrate_render_epsilon.py`; test:
  `test_scripts/test_calibrate_render_epsilon.py` (17 tests).
  Result on maintainer machine (Win11, PyMuPDF 1.27.1, 50 iterations, 96 dpi):
  **zero pixel noise** across all 10 corpus cases.  Recommended ε = 1
  (floor margin).  CI runner measurement deferred to the `commit-fidelity`
  CI job (Phase B) — if CI shows non-zero noise, bump ε there.
- [ ] **Rebind the Stop-hook completion gate** (`scripts/check_completion_proof_hook.py`)
  from its dormant `GOAL_FILE` (`plans/2026-05-05-no-jump-editor-geometry-gate.md`,
  never committed → gate is a permanent no-op) to a new gate plan for this
  engine, so Phase A-D PRs get the independent re-verification the hook was
  built for instead of relying on manual review alone.
- [ ] **`commit-fidelity` CI job** running `verify_commit_fidelity.py` against
  the synthetic corpus (Windows leg blocking, matching the existing
  `test-functional` split) — lands with Phase B.
- [ ] **Perf-budget tests** for `engine.apply` / `render_edit_preview` (the
  300ms slow-edit budget and per-keystroke scratch-doc cost from open question
  6) — target the M3.6 failure class ("So slow" / "Freeze on each operation" /
  500-700MB resident) with an automated gate instead of relying on manual QA
  to catch it a second time.
- [ ] Spikes S2 (TextWriter transplant vs append — 1b is the theoretically
  correct default for z-order but is unproven on resource-dict-collision /
  graphics-state-bleed risk; decide from the render-diff spike, not from
  argument), S3 (Identity-H stream patch), S4 (mapping-ambiguity audit) — each
  its own PR, per plan §4.10.

## Deferred from prior campaigns

### R5-01 / Codex F6 (from post-campaign repair, 2026-06-21) — Resolved in Milestone 2

- [x] **R5-01 fileless print path — Resolved (PR-17, 2026-07-10).** Both plaintext temps are gone.
  `capture_print_snapshot_bytes` always returns `PDF_ENCRYPT_NONE` bytes, so *both* temps held a fully
  decrypted copy of the document at rest.
  - `work_dir/input.pdf` (coordinator): the document now rides the helper subprocess's **stdin**, written
    in 1 MiB chunks with `bytesWritten` flow control. `job.json` carries options + watermarks only.
  - the dispatcher's `NamedTemporaryFile`: `PrintDispatcher.print_pdf_bytes` now calls the new
    `PrinterDriver.print_pdf_from_bytes`. `WindowsPrinterDriver` overrides it, so on Windows **no document
    bytes touch disk at any point**. `PDFRenderer`/`raster_print_pdf` accept `str | bytes`.
  - Bonus: because the piped bytes are already plaintext, the helper has nothing to authenticate, so the
    R5.1 re-encryption and the `PDF_EDITOR_PRINT_PASSWORD` **environment variable are gone from the
    production path** (a process env block is readable by same-user processes; an anonymous pipe is not).
  - Duplicate copies: 5 stops (bytes → input.pdf → helper read → temp → renderer read) reduced to 2.
  - **Residual, accepted:** the Linux/macOS CUPS/lp *direct-PDF* route still materialises one temp, because
    `conn.printFile` / `lp` hand the path to a filter chain that must parse and rasterise it. It cannot be
    encrypted (the consumer needs plaintext), so it is instead driver-scoped, `0600`, and unlinked in a
    `finally`. Windows never reaches that code. Documented in `docs/PITFALLS.md`.
  - Design: `plans/archive/r5-01-fileless-print.md` §11. Tests: `test_scripts/test_print_fileless.py` (+ rewritten
    `test_print_encrypted_input.py`, `test_print_dispatcher_real_sink.py`,
    `test_security_dispatcher_temp_cleanup.py`).
- [x] **Codex F6 — in-flight worker decrypted-bytes lifetime — Resolved (PR-18, 2026-07-10), Exit A.**
  The old note said "revisit only if a worker can be made to clear its payload race-free on cancel." It can,
  and the mechanism needs no synchronisation at all: **the worker clears its own `_doc_bytes` on its own
  thread.** `request_cancel()` (GUI thread) only flips a bool; nothing but the worker thread ever writes the
  payload, so there is no window to lose and the non-blocking cancel is preserved.
  - `_SearchWorker` drops the reference immediately after `fitz.open("pdf", ...)` — PyMuPDF holds its own
    reference to the buffer, so the `Document` stays usable (verified: refcount 3 after open).
  - `_OcrWorker` needs the bytes on every iteration (`ocr_pages(doc=...)`), so it clears in `run()`'s
    `finally`. That still bounds the lifetime to `run()` instead of to the QObject's lifetime, which
    extends past the loop until Qt processes the pending `deleteLater()` — the actual F6 exposure.
  - Fixed en route: `_SearchWorker.run()` called `doc.close()` unconditionally in a `finally`, crashing with
    `AttributeError` on the empty-`doc_bytes` fallback path.
  - **Residual, accepted:** between `request_cancel()` and the worker's next checkpoint, the in-flight page
    still holds the bytes, and the live document is decrypted in RAM regardless. Removing that needs a
    blocking join, which would regress the intentional non-blocking cancel.
  - Tests: `test_scripts/test_worker_doc_bytes_lifetime.py`.

### Audit remediation deferrals (2026-06-10)

- [~] **R4.1 — Overlay render cache: EVALUATED → DEFERRED.** Disproportionate risk for a watermark-only conditional gain. Full rationale: `plans/refactor-R4-performance-deferrals.md`. Revisit only if watermarked scroll-after-edit latency becomes a measured bottleneck.
- [x] **MVC routing of merge-dialog page counting.** The view-layer `fitz.open()` calls in `pdf_view.py` (merge dialog page-count probe) should route through a controller/model utility to respect layer boundaries. **Resolved (R2.3, predates PR-9):** `PDFController.resolve_insert_source_file()` is the routed path; `view/pdf_view.py` has zero `fitz.open(...)` calls (confirmed by `test_scripts/test_layer_boundaries.py`'s exact-count allowlist, which only permits `view/text_editing.py`'s scratch doc).

## Resolved -- Completion-gate trust chain (2026-07-03, Codex adversarial-review finding)

Phase 1 of the setup-optimization campaign (2026-07-02) unregistered the `Stop` hook and, separately, edited
`check_completion_proof_hook.py`'s header comment without cascading the SHA-256 update through
`gate_anchor.py` → `completion_gate.py`'s `_PINNED_HASHES`. Net effect: `scripts/completion_gate.py` could no
longer pass its own Step 0b (missing Stop-hook registration) or Step 0c (stale pinned hash) invariant checks —
a permanently broken trust chain, caught by `codex:adversarial-review --base pre-optimization-2026-07-02`.

Fixed by re-registering the Stop hook in `.claude/settings.json` (alongside the Phase-1 `PostToolUse` ruff
hook) and re-cascading the hash chain (`check_completion_proof_hook.py` → `gate_anchor.py._HOOK_HASH` →
`completion_gate.py._PINNED_HASHES['scripts/gate_anchor.py']`). Verified: the hook still exits 0 in ~90ms
(its `GOAL_FILE`, `plans/2026-05-05-no-jump-editor-geometry-gate.md`, has never been committed to git, so
Layer 1's goal-mode guard short-circuits), Steps 0/0a/0b/0c of `completion_gate.py` now pass, and
`test_scripts/test_completion_proof_hook.py` is green (18 passed, 1 skipped).

- [x] **Open follow-up — Resolved (PR-14, 2026-07-10) as documented-here-instead.** `gate_anchor.py`'s
  maintenance doc (step 5, `scripts/gate_anchor.py:26`) says "document the change in
  `plans/2026-05-05-no-jump-editor-geometry-gate.md`" — that file has never existed in git (a pre-existing
  gap predating this campaign, not introduced by it).

  **This TODOS section is that file's stand-in.** Hash-cascade changes are recorded here.

  Two fixes were considered and rejected:
  - *Edit `gate_anchor.py:26` to point at this file.* Rejected: any content change to `gate_anchor.py`
    changes its SHA-256, which is pinned in `completion_gate.py._PINNED_HASHES`, forcing a hash re-cascade
    for a comment edit. Cost/benefit is upside-down.
  - *Create the missing `plans/2026-05-05-no-jump-editor-geometry-gate.md`.* **Rejected — actively unsafe.**
    `check_completion_proof_hook.py:120-122` deactivates the Stop-hook gate only while `GOAL_FILE` neither
    exists on disk nor is tracked in git. Committing that plan file would flip Layer 1's goal-mode guard on
    and start enforcing Layer 2 (proof/marker/signoff artifacts in `test_artifacts/`) on every Stop event.
    The dangling pointer is inert; the file it points at is a live tripwire.

  If a future no-jump-style campaign revives that plan file, it must (a) reconcile this history into it and
  (b) expect the Stop gate to arm itself the moment the file is committed.

## Resolved -- Layer boundary violations (S4 import-linter, added 2026-07-02)

`lint-imports` (`.github/workflows/ci.yml` → `layer-boundaries`) now runs all four contracts as a single
**blocking** step: `model-no-controller-view`, `model-no-qt`, `utils-no-controller-view-model` (PR-8), and
`view-no-model` (PR-9). No known violations remain.

- [x] **`utils/preferences.py` imports `model.tools.ocr_types`.** Utils importing Model inverts the intended
  bottom-of-stack position of `utils/`. Either move `ocr_types` to `utils/` (if it's really a shared type) or move
  the OCR preference logic that needs it into `controller/`/`model/`. **Resolved (PR-8):** moved to
  `utils/ocr_types.py` with a re-export shim left at `model/tools/ocr_types.py`.
- [x] **`utils/helpers.py` imports `PySide6.QtWidgets.QMessageBox`.** Utils showing a message box directly bypasses
  the View layer; callers should raise/return and let View show the dialog. **Resolved (PR-8):** moved
  `show_error` to `view/message_boxes.py`; all callers updated.
- [x] **View importing Model directly** (`view/dialogs/audit.py`, `view/dialogs/ocr.py`, `view/dialogs/optimize.py`,
  `view/object_selection.py`, `view/pdf_view.py`, `view/text_editing.py`). **Resolved (PR-9, 2026-07-04):** the two
  real boundary crossings were routed through controller injection — `view/dialogs/ocr.py::OcrDialog` takes a
  required `device_available` callable (view forwards to `PDFController.is_device_available`, new facade over
  `model.tools.ocr_tool.is_device_available`), and `view/dialogs/optimize.py::OptimizePdfDialog` takes a required
  `preset_options` callable (`PDFController.start_optimize_pdf_copy()` passes `PDFModel.preset_optimize_options`).
  The remaining DTO/type imports (`model.object_requests`, `model.edit_requests`, `model.pdf_optimizer`) have no
  mutation surface and are permitted via `ignore_imports` on the `view-no-model` contract in `pyproject.toml`,
  each with a comment justifying the permit. `view-no-model` is now blocking.

## Open -- Security dependency hygiene (from F2/F9 patch work; updated 2026-06-05)

See `docs/history/reports/0607-implementation-notes.md` for the full F1-F9 patch log.

### BLOCKED — transformers CVE (investigated 2026-06-05)

`surya-ocr` transitively pulls `transformers 4.57.6` (two CVEs: CVE-2026-1839 fixed only in 5.x, PYSEC-2025-217 no fix). No surya release requires or is validated against transformers 5.x. Do NOT bump. See TODOS-archive for full investigation table.

### Pillow floor vs. surya-ocr

Reconciled via file split: `surya-ocr` + `torch` in `ocr-requirements.txt`; core image features floor at `Pillow>=12.2.0` in `optional-requirements.txt`. Locked by `test_security_pillow_floor.py` and `test_security_ocr_requirements.py`.

### Deployment env remediation — Resolved (PR-13, 2026-07-10)

- [x] **Upgrade the build-env (`.venv`) Pillow to >=12.2.0.** Done. `.venv` measures **Pillow 12.2.0**
  (the 5 image-parser CVEs are remediated); `constraints-ci.txt` pins the same version, so CI and the
  build env agree by policy. The upgrade landed as a side effect of M1 PR-1's constraints capture.
- [x] **Refresh build tooling** in the `.venv`. Done: **pip 26.1.2**, **setuptools 82.0.1**, **wheel 0.47.0**
  (were pip 21.2.3 / setuptools 57.4.0). `constraints-ci.txt` pins setuptools/wheel.
- [~] **PyInstaller rebuild: DEFERRED to the distribution track.** There is no `.spec` file anywhere in
  the repo and no build recipe to rebuild from (`build/` is an untracked distutils artifact, not a
  PyInstaller output). PyInstaller 6.19.0 + `pyinstaller-hooks-contrib` are installed in `.venv`, but
  authoring the spec is distribution work the roadmap already parks under "Later candidates"
  (packaged-EXE embedded icon + PyInstaller spec). The CVE remediation above does not depend on it:
  a future build picks up the patched `.venv` automatically.

### Remaining open items

- [ ] **Revisit the OCR stack when surya-ocr relaxes its pins.** When a surya release ships `pillow>=12.2` support and a transformers floor in the 5.x line, merge `ocr-requirements.txt` back and drop the residual-risk note.
- [ ] **F9 bundle distribution** — ship a vetted weights bundle and populate `WEIGHTS_MANIFEST` with its published SHA256 digests so `PDF_EDITOR_OCR_WEIGHTS_DIR` works out of the box. See `docs/ocr-weights-verification.md`.

## CI coverage baseline (PR-11, 2026-07-05) -- gate enforced in PR-12

- [x] **Evidence-based coverage gate (PR-12).** CI coverage baseline (PR-11, 2026-07-05): 78%
  windows-latest functional leg, stable across 3 consecutive runs (local: 79%).
  CI detail: 15385 stmts / 3354 missed, 1553 passed / 33 skipped / 15 deselected / 0 failed
  (run 28712396725). Local detail: 15385 stmts / 3292 missed.
  Measured by the now-blocking windows `test-functional` leg via
  `--cov --cov-report=term --cov-report=xml --cov-fail-under=0` (the explicit 0 kept the
  number advisory pending this PR). The CI figure is lower than local because fixture-dependent
  (`needs_fixtures`) tests don't run there.
  PR-12 removes the `--cov-fail-under=0` override from the windows leg's cov args, so
  `pyproject.toml`'s existing `[tool.coverage.report] fail_under = 75` now governs on CI —
  one number, one source of truth, three points of headroom against the CI-measured 78%
  baseline. (Deviation from the original plan note below this line, which proposed
  CI-measured-minus-2: 75 was already the configured threshold and already has real
  headroom, so it was left as-is rather than raised, per PR-12 design decision.)

## CI advisory findings (PR-10, 2026-07-04)

- [ ] **ubuntu-latest `test-functional` leg segfaults (Bus error, intermittent).** Crashes inside
  `test_scripts/test_page_deskew_scope.py::test_controller_straightens_batch_as_single_undo` at a
  `qapp.processEvents()` call (~49-58% through the suite), native Qt/PyMuPDF/PIL interaction under
  offscreen rendering; doesn't reproduce on every run (2 of 4 sampled runs completed cleanly). Stays
  advisory (`continue-on-error: true`) until root-caused. See GitHub issue
  https://github.com/CyberSaga/pdf_editor/issues/19 for full evidence and next steps (bisect via
  `--deselect`, junit artifact comparison across runs, core dump analysis).

## Future Object Follow-Ups

- Any remaining object-manipulation polish that needs its own child plan.
- [x] **Delete app-image: drop `PDF_REDACT_IMAGE_REMOVE`** — **Resolved (PR-16, 2026-07-10).**
  The image branch of `_delete_object_impl` (`model/pdf_object_ops.py`, not `pdf_model.py` — the code
  moved) now resolves the marker to its `NativeImageInvocation` via `_resolve_marker_image_invocation`
  and strips only that placement via `_remove_native_image_invocation`, matching the move/rotate
  conversion from `c099b28`. An unresolvable placement fails safe (delete returns `False`, a no-op)
  rather than falling back to redaction.

  The defect was **larger than this item described**. `apply_redactions` is geometric, so deleting an
  app-image also destroyed *text* and *line art* under its rect, not only overlapping images (measured:
  `"UNDER THE IMAGE"` → `"AGE"`). Design + measurements:
  `plans/archive/b1-delete-app-image-invocation-removal.md`; generalized gotcha in `docs/PITFALLS.md`.

  Regressions added to `test_scripts/test_image_objects_model.py` (all synthesized in-test, so the
  blocking Windows CI leg runs them): overlapping-neighbour survival, underlying-text preservation,
  underlying-vector-art preservation, shared-xref neighbour survival, fail-safe on ambiguous
  resolution, undo restores both, save/reopen persistence. `test_pdf_object_ops_transactional.py`'s
  two redaction-injection tests were retargeted at the new mutation call and strengthened to assert
  `apply_redactions` is never invoked on this path.

- [ ] **Content-stream tokenizer has no inline-image (`BI … ID … EI`) mode.**
  `model/pdf_content_ops.py`'s tokenizer lexes inline-image *binary data* as operators: a `0x25` (`%`) byte
  starts comment-skipping to end-of-line, `(`/`<` trigger delimited consumption that can run past `EI`, and
  stray bytes can lex as `q`/`Q`/`Do`, perturbing the q/Q bounds used by `_remove_native_image_invocation`.
  Any whole-stream re-serialize (`serialize_tokens` joins with `\n`) then mangles the image bytes.

  **Pre-existing, not introduced by PR-16:** `_rewrite_native_image_matrix` (move/rotate, `c099b28`) and the
  `native_image` delete branch already re-serialize the same streams. The app-image path cannot reach it
  directly — `insert_image` appends a fresh `q cm /name Do Q` stream per insert. The reachability argument
  runs through `_redact_and_restore_textbox_region` consolidating page contents first, and it is unverified
  whether mupdf's redaction filter re-emits inline images as `BI…EI` at all.

  Fix direction: treat `ID … EI` as one opaque byte token, or fail-safe (`return False` before
  `update_stream`) when a target stream contains `BI`/`ID`. Needs its own red-light suite covering move,
  rotate, and both delete branches. Raised by adversarial review; see
  `plans/archive/b1-delete-app-image-invocation-removal.md` §10.3.

- [x] **B1 codex adversarial review completed (2026-07-12).** The resumed Codex pass reproduced and fixed
  three additional defects: a stale shared-xref marker deleting the surviving placement; an unrelated
  page's same-named XObject preventing inherited-resource pruning and surviving `garbage=4`; and the
  fileless print runner retaining plaintext and never finishing after `QProcess.FailedToStart`.
  Regression coverage lives in `test_image_objects_model.py` and `test_print_subprocess_runner.py`.

- [ ] **Batch delete gives no feedback when it rolls back.** `delete_objects_atomic` is all-or-nothing by
  design, so one unresolvable app-image in a multi-select cancels the whole delete. The view has already
  cleared the selection handles by then, so the user sees the handles vanish and nothing happen — no toast,
  no undo entry. Add a message on the `False` path of `PDFController.delete_object` (both the batch and
  single branches); `_show_edit_result_feedback` is the precedent. UX only; correctness is fine.

- [ ] **A no-op delete used to leave `model.doc` renamed.** Fixed for delete (rollback is now conditional on
  `edit_count` changing), but `_restore_doc_from_snapshot` still yields a doc with an empty `doc.name`,
  which silently degrades the next save from incremental to full (`model/pdf_model.py:3263-3278`). Any
  other caller that rolls back a genuine mutation inherits that. Worth a look when touching the save path.

## Future View Follow-Ups

- [ ] Tune middle-click auto-pan speed/feel after manual validation on long multi-page PDFs.
- [ ] Consider drawing an origin marker for auto-pan so users can see the deadzone anchor more clearly.

## Notes on `objects mode`

- Treat `objects mode` as a separate interaction mode from browse mode and text-edit mode.
- Browse mode keeps its text-selection behavior and should not accidentally start moving objects.
- Objects mode should focus on selecting/manipulating objects:
  - Supported now: rectangles, app-inserted images, and native PDF images.
  - Textboxes stay in text-edit mode.
- Text edit mode focuses on textboxes:
  - Supported: move/rotate/delete/resize/multi-select textboxes, plus editing words.
- The same object identity layer stays shared across the object and text-edit paths.

## M3 — Tranche 3.1 Quick Wins (completed 2026-07-15)

- [x] Scale and center thumbnail rasters across narrow and wide sidebars.
- [x] Re-render every thumbnail after page-count changes; keep bounded invalidation for unchanged counts.
- [x] Make repeated Enter advance completed search results without restarting the search.
- [x] Add Ctrl+W current-tab close while preserving an empty application window after the final tab.
- [x] Make the font-size combo editable with one-decimal commit validation and last-valid restoration.
- Runtime evidence is retained separately from the repository.
- Completion gates: `1673 passed, 21 skipped`; full Ruff clean; mypy clean across 35 model/utils files.

## M3 — Tranche 3.2 Platform and Print (implementation complete 2026-07-15)

- [x] Centre raster output on the physical paper rectangle rather than a potentially asymmetric printable rectangle.
- [x] Retain the touched-precedence print contract through dialog/options/helper/Qt bridge tests; no code defect reproduced in the cold-start diagnostic path.
- [x] Grant the already-running Windows instance foreground rights before forwarding a double-click file-open request.
- [x] Log a nonfatal warning when the configured runtime application icon is unavailable.
- [x] Manual verification round 1 (2026-07-17) found two defects; both fixed same day:
  - Print dialog forgot in-app settings between prints in the same process. `PrintCoordinator` now captures accepted-dialog settings (`capture_user_settings()`) and replays them via `previous_settings=`; restore runs **after** `_wire_signals()` so restored hardware fields are touch-marked and beat driver preferences in `_build_effective_options()` (see PITFALLS: "programmatic combo restore must run AFTER signal wiring"). Cancel persists nothing.
  - PgUp/PgDn dead after foreground handoff into a new/detached window (F2/F3 worked — they're window-level QActions; paging needs `graphics_view` focus). `handle_forwarded_cli` and `create_detached_window` now set `graphics_view.setFocus(ActiveWindowFocusReason)` after raising, *after* the `open_pdf` loop so loading can't steal it.
  - Tests: `test_m3_print_settings_persistence.py` (10), `test_m3_forwarded_cli_focus.py` (2).
- [ ] Manual re-verify (blocked items now unblocked): second-print settings retention, cancel-does-not-persist, PgUp/PgDn in a fresh detached window.
- [ ] Capture manual Windows evidence for cold-first-job print overrides and the current source-vs-packaged icon scope.

## M3 — Tranche 3.3 Page Structure (complete)

- [x] Add strict, 1-based custom range validation to delete and rotate dialogs; invalid, reversed, blank, and out-of-range values do not emit mutations.
- [x] Delete all pages transactionally into a single model-side blank placeholder, replacing it when real imported pages arrive and preserving the state over undo/redo.
- [x] Implement thumbnail drag/drop page reordering with snapshot undo/redo, interval-limited thumbnail refresh, stale-index maintenance, and a compact portrait row cap that keeps three drop targets visible.
- [x] Make native thumbnail drags reach the viewport, reorder rows without Qt post-drag deletion, and auto-scroll while hovering within 48 px of the top/bottom edge. Real-GUI acceptance used `test_files/test-colored-background.pdf`.

## M3 — Tranche 3.4 Shell and Tab UX (complete)

- [x] Support a real 720×520 outer shell; below 900 px, collapse both sidebars while preserving at least a 360×300 central viewport, then restore prior sidebar visibility at normal widths.
- [x] Replace style-dependent native tab close glyphs with explicit themed 20×20 `×` controls that delegate to the existing unsaved-tab close pipeline.
- [x] Add saved-tab `開啟檔案所在位置` context action through a session-id View signal, controller metadata resolution, and argument-list platform launcher.
- [x] Route PgUp/PgDn/Home/End from the browse canvas to bounded page targets without stealing keys from text inputs or inline editors.
- [x] Persist a canonical, deduplicated ten-entry recent-file list after successful opens from every existing entry path; show missing entries disabled in the Open menu.

## M3 — Tranche 3.5 Editing Tools (complete)

- [x] Add top/right/bottom/left midpoint resize handles; edge drags change one dimension only, preserve the opposite edge, enforce minimum size, and leave Shift aspect locking corner-only.
- [x] Replace the rectangle fill confirmation with inspector-owned stroke color, optional independent fill color, validated 0.1–20 pt border width, matching preview, persisted object payload, and snapshot undo/redo.
- [x] Add underline and strikeout modes through View signals, controller snapshots, and ToolManager-owned PyMuPDF annotation creation.
- [x] Combine underline/strikeout into a single "標記線" (`markup_line`) mode with a style toggle, replacing the two separate toolbar buttons; each style remembers its own color/opacity independently.
- [ ] `markup_line` line width control (deferred): PyMuPDF's Underline/StrikeOut annotation subtypes reject `set_border()` outright — there is no width to adjust. A real width control needs a design decision on switching to a generic Line annotation positioned at the underline/strikeout Y-offset (gains width control, loses semantic Underline/StrikeOut recognition in other PDF readers).
- [x] Add a title/author/subject/keywords metadata editor with Qt-free model wrappers, preservation of unedited metadata, dirty-tab refresh, save/reopen persistence, and snapshot undo/redo.

## M3 — Performance Baseline (captured 2026-07-15, pre-tranche-3.0)

Full commands, method, and values: `plans/archive/2026-07-16-m3-render-offload.md`.

| Metric | Run 1 | Run 2 |
|---|---:|---:|
| PDFModel import | 0.245 s | — |
| PDFModel instantiation | 0.001 s | — |
| reference fixture| 861.3 ms | 923.7 ms |
| reference fixture| 18.7 ms | 18.4 ms |
| complex fixture| 1252.6 ms | 1044.1 ms |
| complex fixture| 56.8 ms | 52.4 ms |
| complex fixture| 81991.4 ms | 107464.7 ms |

- [x] Fix `benchmark_ui_open_render.py` for the profile-scoped quality map.
- [x] Capture the pre-M3 baseline and seed `plans/archive/2026-07-16-m3-render-offload.md`.
- [x] Re-run immediately before tranche 3.6 and publish before/after evidence.

## M3 — Tranche 3.6 Render Offload (render slice implemented 2026-07-16)

- [x] Profile the complex fixture: XREF repair was absent; snapshot capture was ~1.1 s; page-25 display-list plus raster was ~0.45 s.
- [x] Identify the actual 78–80 s defect as GUI-callback prefetch blocking plus full-document thumbnail contention, not the requested high-quality page raster.
- [x] Add a one-worker/latest-pending `PageRenderCoordinator` with immutable snapshot bytes, QImage-only results, complete token/session/generation/revision/page/scale/profile/DPR rejection, and bounded cancellation.
- [x] Keep the immediate low first paint synchronous; offload high and non-immediate low/prefetch rendering; pause and resume thumbnails around foreground candidates.
- [x] Reduce complex midpoint jump readiness from 78.1/80.1 s to 180.5/167.5 ms; full commands and raw values are in `plans/archive/2026-07-16-m3-render-offload.md`.
- [x] Center mixed-width continuous pages through shared per-page x/y coordinate helpers and add browse-mode run-local numeric-token double-click selection.
- [x] M3.6 completion gates: `1788 passed, 21 skipped`; full Ruff clean; mypy clean across 36 model/utils files.
- Manual verification round 2 (2026-07-17) found two defect clusters; investigation in `plans/archive/2026-07-17-m3-manual-round2-defects.md`:
  - [x] Annotation placement offset on rotated pages (下右偏移) — PyMuPDF interprets `add_*_annot` geometry (and stores `/Rect`) in **unrotated** page space while the app deals in displayed coords; HVAC fixture pages are rotation=270. Fixed at the model-boundary chokepoint in `annotation_tool.py`: derotation on write (corner-mapped quads for highlight/underline/strikeout, anchor-point for note `set_rect`), `rotation_matrix` on read in `get_all_annotations`. `add_redact_annot` verified rotation-safe (text editing unaffected). Tests: `test_annotation_rotation.py` (24, pixel-detection oracle — `annot.rect` readback lies).
  - [ ] Manual re-verify: rectangle/highlight/underline/strikeout placement, note-marker position, and jump-to-note on the rotated HVAC fixture pages.
  - [ ] Render responsiveness/memory cluster (zoom slow, freeze on high/prefetch/tab switch/close, 500–700 MB): root-caused — PyMuPDF holds the GIL during rendering (measured 4.5 s main-thread stalls while a "background" QThread rastered), so the M3.6 QThread offload cannot free the UI on dense fixtures; plus 220 ms+ synchronous low render per zoom step and 52 s/+155 MB full-document thumbnail sweeps. Fix needs its own plan: out-of-process rasterization (pattern: `src/printing/subprocess_runner.py`), rescale-don't-re-raster on wheel zoom, on-demand thumbnails.
- [x] UNC recent-files crash (found and fixed 2026-07-17): Python 3.10 `Path.resolve(strict=False)` raises WinError 53 on unreachable UNC paths; a stale network-share entry crashed `activate()` → `_refresh_recent_files()` and a second path via `open_pdf()` → `find_session_by_path()`. Fixed at chokepoints catching only `OSError` with a string-canonical fallback: `_safe_resolve_path` (preferences), `PDFModel._canonicalize_path`, per-entry `available=False` defense in `_refresh_recent_files`; `single_instance` sender/receiver made explicitly FAIL-CLOSED (unresolvable token rejects the whole hand-off/message — never skipped). Tests: `test_recent_files_unc_robustness.py` (6, red-on-revert verified); previously-failing suites went 8 → 0. See PITFALLS entry.
- [ ] Follow-up (audited 2026-07-17, lower severity, no failing test yet): inline `Path(...).resolve()` sites without OSError guards — `pdf_model.py` `open_insert_source` (~1700), `open_merge_source` (~1756), `_atomic_full_save` (~3078), `_full_save_to_path` (~3479, resolves `doc.name` — raises mid-save if the source share died), `save_as`/`save_session_as` (~3603/~409), `pdf_controller.py` optimize dedupe (~1485), `src/printing/dispatcher.py` output path (~101). Route through a shared safe-resolve helper when touched.
- [ ] Test-isolation gap: suites construct controllers that read the REAL user preference store (`UserPreferences()` default QSettings), so machine-local state can poison unrelated tests — point tests at an isolated store fixture.

## M3 — Tranche 3.7 Notes and Bookmarks (implementation complete 2026-07-16)

- [x] Create compact standard PDF Text notes; list legacy FreeText read-only; snapshot-back content update, marker move, and delete.
- [x] Add a main-window-owned frameless `FloatingNote`; popup drag remains UI-only while marker drag persists through a View signal and controller snapshot.
- [x] Add validated Qt-free TOC get/set APIs and remap bookmark targets across insert, delete/delete-all placeholder, and final-index page moves.
- [x] Add nested bookmark tree navigation plus add/rename/delete/sibling-reorder requests through the controller-owned TOC snapshot path.
- [x] M3.7 completion gates: `1800 passed, 21 skipped`; full Ruff clean; mypy clean across 36 model/utils files.
- Manual verification (`docs/M3-Manual-Verification-Checklist-0716.md`) found bookmark rename/page-edit undiscoverable and the note drag bar not visibly grabbable — both fixed 2026-07-17:
  - [x] Rename a bookmark — was implemented (`Qt.ItemIsEditable` + `_on_toc_item_changed`) but only reachable via F2 (`EditKeyPressed`), with double-click already claimed by navigation; added a right-click context menu on `bookmark_tree` ("重新命名" → `editItem(item, 0)`). Tests: `test_scripts/test_bookmark_rename_ux.py`.
  - [x] Change its page number — same undiscoverability; added "設定頁碼" → `editItem(item, 1)` to the same context menu, reusing existing validation/clamping in `_on_toc_item_changed` unchanged. Tests: `test_scripts/test_bookmark_rename_ux.py`.
  - [x] Note popup drag handle polish (希望可以抓到註解的那個可點擊區域是可見的) — `_NoteDragBar` (`view/floating_note.py`) now has a visible background/border and an open-hand cursor. Tests: `test_scripts/test_floating_notes.py::test_note_drag_bar_is_visually_identifiable_as_a_grab_handle`.
- Manual verification (round 2) found the note popup was not session-scoped — fixed 2026-07-18:
  - [x] Note popup survives its own delete — `FloatingNote` delete button only emitted `delete_requested`, never `.close()`d, leaving it editing a deleted xref; now `_emit_delete` closes it (relies on `WA_DeleteOnClose`). Tests: `test_scripts/test_floating_notes.py::test_delete_button_closes_the_popup`.
  - [x] Note popup survives tab-close / tab-switch and mutates the wrong session — `_floating_note` was an un-scoped singleton, so its Save/Delete/drag (routed via the controller to `_record_annotation_mutation`) hit whatever `get_active_session_id()` currently pointed at, not the popup's origin session — a silent cross-document corruption path. Now the view records `_floating_note_sid` on open and `_dismiss_floating_note_if_orphaned()` (called from `set_document_tabs`, the funnel for every switch/close/reset) closes it the instant its owning session stops being active. Tests: `test_closing_the_popups_owning_tab_dismisses_the_popup`, `test_switching_away_from_owning_tab_severs_the_cross_session_mutation_path`.
  - [x] Bookmark panel doesn't clear when the last tab closes (有保留。但關閉分頁後書籤不會消失，要關閉視窗才會) — `_reset_empty_ui()` cleared the annotation and watermark lists but had no `populate_toc([])`, so stale bookmark rows from the last-closed document lingered until the whole window closed. Added the missing `self.view.populate_toc([])` call alongside the existing list-clearing pattern. Tests: `test_scripts/test_bookmarks_toc.py::test_reset_empty_ui_clears_bookmark_panel`.
  - [x] Bookmark deselected on every up/down move (每按一次上移或下移就會取消聚焦該書籤，還要重新點一次太麻煩) — `_move_selected_bookmark` set the current item then emitted `sig_toc_changed`, whose synchronous round-trip (`update_toc` → `load_toc` → `populate_toc`) does a full `tree.clear()`+rebuild, destroying the just-set selection before the event loop ran. The view now stashes the moved entry's flat DFS index (`_pending_toc_selection`) and re-selects/focuses the matching rebuilt item at the end of `populate_toc` (`_restore_pending_toc_selection`); scoped to the move path only. Tests: `test_scripts/test_bookmarks_toc.py::test_move_bookmark_up_preserves_selection_after_rebuild`, `test_move_bookmark_down_preserves_selection_after_rebuild`, `test_move_child_bookmark_preserves_selection_after_rebuild`, `test_move_bookmark_boundary_noop_leaves_selection_intact`.

## M3 — Tranche 3.8 Tab Detachment (implementation complete 2026-07-16)

- [x] Add true thresholded tab drag-out through `DetachableTabBar`; clicks/short/in-bar drags do not detach.
- [x] Transfer repr-safe in-memory snapshot/path/dirty/page/zoom/profile DTOs into an independent MVC triple composed only by `main.py`.
- [x] Remove the source session only after destination readiness; failed handoff leaves the source intact.
- [x] Preserve dirty state through a session-local flag and normal save; intentionally start the detached undo stack empty.
- [x] Final automated gates: `1804 passed, 21 skipped`; full Ruff clean; mypy clean across 36 model/utils files.
- [ ] Manual acceptance remains: drag saved and dirty tabs into secondary windows, save/reopen, and close both windows independently.

## M3 candidate — Acrobat-stable text commit engine V2 (design corrected 2026-07-18)

Implementation plan: `plans/2026-07-18-acrobat-stable-text-commit-engine-v2.md`.
The earlier `plans/archive/2026-07-14-acrobat-parity-text-commit-engine.md` is retained as
superseded design archaeology. The diagnosis remains: font/layout changes are the
structural ceiling of redact+reinsert, not a collapse of the May five-layer editor-open work.

- [x] Diagnosis + base-vs-main regression audit (commit engine unchanged; one continuous-mode placement change is unrelated to general post-commit font/reflow changes)
- [x] Adversarial design review — corrected lossless stream, text-advance, TextWriter resource identity, scratch-first verification, save/cleanup, and unsupported-PDF assumptions
- [x] Spike S1 — font round-trip audit over corpus (embedded TT/Type0: 100% extract+load)
- [x] Task 1 — deterministic synthetic fidelity corpus (merged via PR #26) + 5 strict-xfail characterization tests (`test_scripts/test_text_commit_characterization.py`, 2026-07-18): Base-14 substitution, scalar-font style truth, fast/htmlbox pixel divergence, neighbor push-down, line-break rewriting
- [x] Task 2 — lossless byte-range lexer/raw splice (`model/text_commit/pdf_lexer.py`; tiles source exactly incl. trivia/inline images; splice gated on digest+expected-bytes+overlap+range; no serializer by design)
- [x] Task 3 — horizontal page-stream text-state replay + source binding (`replay.py`/`inspect.py`; multi-stream state carry, per-stream byte ranges, stable RejectReason refusals) + read-only audit `scripts/audit_text_source_mapping.py` (synthetic corpus: 14/18 spans bound; CID/GID and rotation reject honestly)
- [x] Task 4 — per-xref font registry (`fonts.py`; keyed by generation/owner/name/xref; explicit face provenance; Type3//Differences/Identity-H tier0 reject codes; strict-ASCII verified reverse encoder; no silent Helvetica anywhere)
- [x] Task 5 — StyleOverrides (view populates only user-touched fields) + CommitStatus/Tier/FontOutcome/CommitOutcome + EditTextCommand stores outcome & gates Track A/B reflow on `allows_external_reflow` + TextCommitSettings (TEXT_COMMIT_* env) injected in main.py; defaults legacy/off
- [x] Task 6 — Tier 0 LOSSLESS_STREAM_PATCH (`plan.py`/`patch.py`/`verify.py`/`engine.py`): whole-Tj equal-advance Latin gate, scratch-first prepare, fingerprint-checked single PatchSet, V0a–V0e verification incl. exact raster identity outside 2pt halo, revert-on-failure, STALE_PLAN without mutation
- [x] Task 7 — shadow/tiered integration + maintenance policy (2026-07-19): `edit_text` hook behind `legacy|shadow|tiered` (shadow logs sanitized reason codes only; tiered commits Tier 0 with zero legacy machinery, falls back with `tier0:<reason>` chain, strict mode returns `REJECTED_STRICT` without mutation); `mark_page_content_dirty` chokepoint replaces all 9 direct `pending_edits.append` sites and revokes fidelity protection; `apply_pending_redactions` skips fidelity-protected pages. Note: block-manager runs are word-level — Tier 0 target = whole line (space-joined runs) or single whole-word run
- [x] Task 8 — exact plan-backed preview: `model/text_commit/preview.py` (one snapshot per edit session, session-scoped scratch renderer, content-derived plan token) + `controller/text_commit_coordinator.py` (session-long QThread worker, latest-wins, session/generation/identity staleness guards) + emit-only View hook (`sig_text_edit_plan_preview`) + `plan_token` carried into EditTextRequest; gated by TEXT_COMMIT_PREVIEW=plan; new gate file in verify_no_jump PYTEST_TARGETS
- [x] Task 9 — persistence + undo/redo + unsupported boundaries (2026-07-29): `test_text_commit_persistence.py` (7) + `test_text_commit_boundaries.py` (7). Tiered mode hard-rejects widget/signed pages up front (`REJECTED_UNSUPPORTED`, zero mutation) instead of silently degrading to legacy; Tier 0 undo/redo replay a validated forward/inverse PatchSet pair (`patch.py:build_reversal_patchset`) — undo restores byte-identical streams + annotations + `fidelity_protected_pages` membership, redo reproduces the exact committed bytes or fails `STALE_PLAN` with zero mutation; encryption preserved: `engine.py:_build_scratch_copy` + V0e probe now serialize with `PDF_ENCRYPT_KEEP` (the default-`tobytes()` calls were corrupting the live crypt state — see PITFALLS); `_capture_page_snapshot` restores annotation `/P` keys stripped by `insert_pdf` (pre-existing, engine-agnostic defect). Follow-up: `preview.py` still has one default-`tobytes()` call site (same encrypted-doc risk, untested)
- [x] Task 10 — Tier 1 spikes, no production enablement (2026-07-30): go/no-go recorded in plan Step 6 — advance-preserving erase GO (`patch.py:build_advance_preserving_erase`, kern-only `[N] TJ` compensation exact to 0.1pt), append NO-GO terminal (z-order/clip/OCG/gs-bleed failures structural to appending at end of `/Contents`), source-position transplant GO (`patch.py:build_transplant_replacement` inherits z-order/clip/ExtGState/OCG by construction; not advance-neutral alone — layer in erase math), font honesty GO (`patch.py:build_tier1_font_outcome` gated by `verify.py:prove_source_resource_reuse` xref-identity proof), Identity-H PARTIAL (evidence reader `verify.py:collect_cid_encoding_evidence` GO; enablement stays deferred; missing `/ToUnicode` = hard `FONT_UNSUPPORTED_ENCODING`, never Unicode-coverage inference). New: `test_text_commit_textwriter_zorder.py` (3), `test_text_commit_identity_h_spike.py` (2), `scripts/audit_tier_coverage.py` (read-only counts-only tier audit). Tier 1 remains flag-off
- [x] Task 10a — structural-gate test hardening (2026-07-31, from a test-validity audit): mutation testing proved `plan.py`'s `mc_depth` and `render_mode`/`rise`/`hscale` gates could both be **deleted with the whole suite still green** — the existing tests asserted only that the *replay recorded* the state, never that the *planner rejected* it, and every case in `test_text_commit_tier0.py`'s rejection test varies only the request, never the document. New `test_scripts/test_text_commit_structural_gates.py` (9 tests) covers all nine structural gates at planner level: mc_depth, render_mode, rise, hscale (plan.py), in_bt, origin_reliable→`UNTRACKED_ADVANCE`, trm_translation_only via **uniform scale** (the TeX/dvips `1 Tf` + `10 0 0 10 … Tm` idiom, previously only rotation was covered and only at bind level), and both `FONT_FACE_UNAVAILABLE` routes. Each test pins reason **and** a detail substring (four gates share `UNSUPPORTED_TEXT_STATE`, two share `FONT_FACE_UNAVAILABLE` — reason alone lets a test survive its own gate's deletion), asserts the fixture is off-nominal in exactly one field, and replays a positive control. All nine mutation-verified SENSITIVE. First assertions anywhere for `UNTRACKED_ADVANCE` and `FONT_FACE_UNAVAILABLE`
- [x] Task 10b — encrypted-document safety in the preview/verify paths (2026-07-31, Red-light first): `preview.py:open_preview_session` and `verify.py:_ocg_membership_lost` both called `tobytes()` with the default (decrypting) encryption on the *live* handle, silently poisoning its crypt state so the user's next `PDF_ENCRYPT_KEEP` save wrote streams that no longer decrypt. Both measured, not theoretical — 4 of 5 new tests failed before the fix with `needs_pass` 1→0 on reopen. Fix follows the proven `PDFModel._decrypted_snapshot_bytes` shape: KEEP snapshot → throwaway clone → authenticate → decrypt the clone, whose crypt state nobody depends on. `open_preview_session` now takes `password` and returns `PreviewSessionInput | None`; the controller threads `model.password` and degrades to the legacy preview with a new `snapshot_unavailable` reason rather than claiming exactness. New `test_scripts/test_text_commit_encrypted_safety.py` (5) also pins the property a lazy fix would break — the snapshot stays plan-valid, i.e. a `PreparedEdit` prepared on it still addresses the same bytes in the live encrypted document
- [x] Follow-up from Task 10b: `_ocg_membership_lost` → tri-state `_ocg_membership_status` (`preserved` / `lost` / `unknown`) across locked-probe and every exception path (WS-D, 2026-08-03). Unknown is never recorded as `ocg_membership_preserved`. Bool wrapper retained for callers that only need confirmed loss.
- [x] Task 10c — `TextBlock.text` no longer fuses soft-wrapped lines (2026-07-31, Red-light first): `_parse_block` flattened every span of every line into one `"".join`, deleting the word boundary at each line break — a three-line paragraph read back as `"fox jumpsover the lazy dog whilecarrying"`, with `"jumps over"` absent entirely. Concatenating *spans* is correct (contiguous style runs within a line); concatenating *lines* is not. New `_join_visual_lines` inserts a single space between lines, suppressed after a trailing space/newline/hyphen (hyphen = split word) and skipping empty lines, which brings `_parse_block` in line with `_build_paragraphs` (`:560-567`) and `pdf_text_edit.py:1223`. Worth noting the value is `SequenceMatcher`-compared against `page.get_text("text", clip=...)` at `pdf_text_edit.py:456-459`, which *does* separate lines, so the fused form was depressing that ratio and could trigger spurious page-index rebuilds. 4 new tests in `test_text_block_parsing_extraction.py` (1 Red before the fix; 3 constrain it against over-correction: no span-level splitting, hyphen continuation, no double-spacing)
- [x] Task 10d — Tier 0 measures advance from `/Widths`, not from a font face (2026-08-01, Red-light first): the corpus audit found 29,526 of 38,540 shows (76.6%) refused `font_face_unavailable`, all one profile — unembedded TrueType Arial/Times New Roman/Courier New, WinAnsi, Word's default export. None is base-14, so no face resolved. But for a simple font `/Widths` **is** the layout contract, and every one of those fonts carried a complete table. New `_read_width_table` + `FontCapability.advance_source`/`first_char`/`widths`; `plan.py:_advance` sources width from the table. Proof `/Widths` outranks the font program: embed a real `arial.ttf` but write `/Widths` all-1000 — MuPDF lays out 40.0pt while the extracted face says 23.32pt. So this is also a soundness fix for the 22 embedded corpus capabilities that were being measured from the wrong source. New reason `FONT_WIDTHS_INCOMPLETE`; malformed tables never downgrade to "absent". `font_face_unavailable` 29,526 → 0, with zero fonts newly refused
- [x] Task 10e — hardening from independent review of Task 10d (2026-08-01, Red-light first, 3 tests in `test_text_commit_widths_hardening.py`): (i) **glyph coverage was bypassed** — with `/Widths` and no face, `missing_glyphs` returned "" for any text, so Tier 0 would commit replacements whose glyphs do not exist, rendering tofu; V0a–V0e cannot catch it because raster identity is asserted *outside* a 2pt halo around the target. A width proves an advance, not an outline. Now only non-subset unembedded fonts (drawn via a substituted complete face) are trusted without a face; 55 of 174 accepted corpus capabilities correctly refuse. (ii) **dangling `/Widths` ref crashed** — unguarded `xref_object` raised `RuntimeError` out through `engine.prepare` and the per-keystroke preview worker, where the pre-change code returned a clean rejection; same latent bug fixed in `_has_custom_differences`. (iii) **the advance tolerance equalled one `/Widths` unit** (`1e-3*size` vs `size/1000`), so float representation decided accept/reject — measured non-monotonic, committing a 0.600pt shift at size 600. `/Widths` arithmetic is exact, so it now gets a float-noise tolerance
- [x] Task 10f — five rounds of independent Codex review over Task 10d/10e, each finding a further layer of the *same* mistake: inferring a property from evidence that does not prove it (2026-08-01, 13 tests in `test_text_commit_widths_hardening.py`, each Red first). R1 `/Widths` attests glyphs → it proves an advance, not an outline. R2 non-subset+unembedded ⇒ substituted complete face → if the named font *is* installed the viewer uses it, and it may be symbolic; replaced with a closed full-ASCII family allowlist plus the descriptor's own `/Flags`. R3 the symbolic flag lives in an indirect descriptor → `/FontDescriptor` may be an inline dict. R4 `/Flags` is a literal → it may itself be `N 0 R`, and the regex was reading the *xref number* (my own test passed only because the allocated number happened to have bit 3 set — made deterministic); plus StandardEncoding disagrees with ASCII at 0x27/0x60 (`quoteright`/`quoteleft`), indirect `/FirstChar`//`LastChar` were misread as malformed, and `/Widths` tokenisation was unbounded in the per-keystroke path. R5 the staleness fingerprint did not cover `/Widths` at all, so a plan measured against old widths passed the freshness check; plus the token bound still materialised the full list. R6 the fingerprint followed `/Widths` but not `/FirstChar`//`LastChar`//`Encoding`//`FontDescriptor`, each of which may also be indirect — replaced ad-hoc enumeration with an auditable dependency-key list. R7 the descriptor `/Flags` were read by regex over the serialised object, which a string value like `/FontFamily (/Flags 0)` defeats; **the recurring root cause across R3/R4/R7 was parsing PDF dictionaries with a regex**, so the regex was removed entirely in favour of PyMuPDF's structured path lookup `xref_get_key(font_xref, "FontDescriptor/Flags")`, which resolves inline-or-indirect descriptor *and* inline-or-indirect flags in one call. R8 a font dictionary stored inline in `/Resources` reports xref 0, and every xref call against it raises out through the per-keystroke path — guarded in all three readers. Corpus outcome identical through all eight rounds (174 accepted / 119 encode / 55 glyph-refused), so none of the safety work cost real coverage. Review stopped at R8 by request; R8's fix went in without a further review pass
- [ ] ~~**Scoping correction — the matrix/operator gates are NOT dead.**~~ **SUPERSEDED 2026-08-01** — the 5,879 figure and the "single-item `TJ` takes `1.pdf` 0/26 → 26/26" claim below both rest on the unsound `array_item_count == 1` rule; the sound decomposition (5,688 hex `Tj` + 165 literal + 0 sound kernless `TJ`) and the phased plan replace them. Kept for provenance; read the phased blocks below instead. Original text:
  **Scoping correction — the matrix/operator gates are NOT dead.** The earlier "trm+op relaxation buys only 137 shows (0.36%)" was measured while the font gate was masking it; the gates were co-blocking. With Task 10d landed, P3 (+uniform_scale +tj_equiv_ops) is worth **5,879 shows (15.25%)**, a 43x change. Two caveats before acting: that figure uses an `array_item_count == 1` TJ rule that is **unsound** as specified (`[-100 (A)]` has one string item but its leading kern shifts the origin — needs a no-kern check, not an item count), and relaxing the trm gate would invert `test_planner_rejects_uniformly_scaled_text_matrix`, which is a deliberate design decision, not an implementation detail. P0 under the *current* policy is still 0: no show fails only the font gate
- [ ] Open defects from the same audit, not yet fixed: (a) Tier 0 is inert on all 6 `test_files/` PDFs (0 eligible of ~38,500 shows) — dominant blocker is the exact-identity text-matrix gate rejecting *uniform scale*, stricter than the plan, which only defers rotation/shear; accepting single-item `TJ` would take `1.pdf` from 0/26 to 26/26. (b) `MULTI_SPAN_TARGET` (`pdf_text_edit.py:1296,1364`) still has no assertion anywhere — it is above the planner, so it needs a different harness than the gate tests. *(Both folded into the phased panel-review block below: (a) → pre-Task-11 D1, (b) → pre-Task-11 D5.)*
- [x] **Panel review 2026-08-01** — three independent models (Opus/Sonnet/Haiku, serial, each told to refute the "structural relaxations are capped by equal-advance" verdict) returned unanimous *partially refuted*: the recommended order stands, the reasoning did not. Two corrections: (i) real edit classes pass the advance gate **deterministically**, not by coincidence — `plan.py:_advance` is a pure multiset function of the text (Σ per-code `/Widths` + Tc·len + Tw·spaces), so transpositions (`teh`→`the`) have delta exactly 0.0; digit-for-digit edits are advance-preserving wherever the font declares tabular figures (verified for Helvetica in `test_text_commit_font_widths.py`; corpus Word-export fonts unverified). The P=0.39 uniform-random-swap statistic measures neither class. (ii) The equal-advance rule is a v1 *policy*, not a ceiling — the plan invariant already licenses "an independently verified compensation operation", and `build_advance_preserving_erase` + `build_transplant_replacement` compose to `[(newtext) K] TJ` with no layout engine (= Task 11 Slice 1). Remaining work reorganized into the three phased blocks below; details in the plan's Task 11 amendment (2026-08-01)

### Pre-Task-11 (do in this order, before any layout work)
- [x] **D5 — direct tests for `_tier0_target_from_resolve` (2026-08-01, Red-light first): 11 tests in `test_scripts/test_tier0_target_resolution.py`, the first direct coverage this stage has ever had.** The defect is real and now measured: word runs are `.strip()`-ed in `text_block_parsing.py:_finalize`, so the `" ".join` at `:1223` reproduces the source only when every gap was exactly one space. `"Price is  100"` rebuilt as `"Price is 100"` fails `bind_source_text`'s byte equality (`inspect.py:233`) and surfaced as `no_source_match` — byte-identical to the refusal for text that is genuinely absent, which is why the class was invisible to every corpus number (the audits classify *shows*, not *edits*). Fix: `_tier0_target_from_resolve` returns `_Tier0Target` carrying `joined_runs`, and a run-joined target failing only `NO_MATCH` is re-labelled `TARGET_RECONSTRUCTION_UNVERIFIED` (new `RejectReason`) at both call sites — the reconstruction is named as the suspect instead of the document. Also the first assertions anywhere for `MULTI_SPAN_TARGET`, at both `:1296` and `:1364`, the latter proving zero mutation on the live-document path. **Mutation-verified (7 mutants):** empty-members guard SENSITIVE, full-line set-equality SENSITIVE, the re-label in both directions SENSITIVE (keep-original *and* relabel-every-miss), `joined_runs` source SENSITIVE, and the `_attempt_tiered_commit` call site SENSITIVE. Two mutants initially SURVIVED and both were real: the `any(...)` line-identity guard (subsumed — see next item), and the commit-path call site, which the classify-path tests were covering *for* it, since mutating a shared helper does not prove each caller invokes it. The latter is now pinned by a dedicated test; the former cannot be
- [x] **DECIDED 2026-08-04 — keep as deliberate defence-in-depth.** The guard stays, with a comment at `model/pdf_text_edit.py:1478-1484` recording the decision, why mutation testing marks it insensitive, and an explicit instruction not to fabricate a fixture for it. Rationale: its protection must not hinge on `span_id`'s format staying byte-identical across two independent parsers — that is an incidental property of today's code, not a contract. Cost is one `any()` over a member list already in hand. Original item:
  **The `any(...)` line-identity guard in `_tier0_target_from_resolve` is subsumed, not pinned** (found by D5 mutation testing). Deleting it leaves the whole suite green: `span_id` is `f"p{page}_b{block}_l{line}_s{idx}"` in both parsers, so a member on another line always carries an id absent from `first`'s `line_run_ids`, and the full-line set-equality check below refuses the same input first; with one member `any(...)` compares `first` to itself. Kept as cheap defence-in-depth and the test docstring no longer claims to pin it. Decide deliberately: delete it, or give it a reachable role. Do **not** fabricate a fixture that makes it look SENSITIVE
- [x] **CLOSED 2026-08-04 (Red-light first).** Note the description below is stale in one detail: by the time this was picked up, `derive_tier0_preview_target` already returned a full `_Tier0Target` (the whitespace-recovery work above changed it) — the residual gap was the *DTO chain* discarding the provenance, not the derivation dropping it. Closed by threading `whitespace_reconstructed` through `controller/pdf_controller.py:3595` → `text_commit_coordinator.request(whitespace_reconstructed=)` → `PlanPreviewRequest.whitespace_reconstructed`, where the renderer relabels a bare `NO_MATCH` to `TARGET_RECONSTRUCTION_UNVERIFIED` exactly as the commit path does. Shadow-mode reason counts collected through the two paths are now comparable. Original item:
  **Preview path still reports the undifferentiated `NO_MATCH` (asymmetry knowingly left by D5).** `derive_tier0_preview_target` (`pdf_text_edit.py:1280`) drops `joined_runs` to keep its 3-tuple contract, so a multi-space line reports `target_reconstruction_unverified` on commit but plain `no_source_match` in the per-keystroke preview — two answers for one condition. No user-visible or correctness difference (both degrade the preview, neither mutates); it is a telemetry/diagnosis inconsistency, and the shadow-mode reason counts the measurement pass will collect come through *both* paths, so fix it before trusting those counts. Closing it means threading the field through `controller/pdf_controller.py:3565` → `text_commit_coordinator.request` → `preview.py:191`, i.e. the QThread worker boundary the plan already lists as needing its own contract work — deliberately not done inside a test task
- [x] **CLOSED 2026-08-04 (opus design → sonnet implement, Red-light first).** Both blockers answered rather than assumed away. `_Tier0Target` gained `source_kind` (`"run_join"` | `"dict_line"`) + `replacement_for(edited)`, and `_dict_line_for_runs` resolves the dict line for a run set behind a **runtime** content-and-geometry alignment proof (gates P1–P5 / A1–A2 / G1–G4) instead of relying on the rawdict↔dict index-alignment assumption blocker (a) named below — the alignment is verified per call, so the shapes where it breaks (multi-span lines, `_parse_block`-skipped blocks, multi-line blocks) refuse instead of mis-binding. Blocker (b), single-run padding, is covered because the dict line carries the leading/trailing padding verbatim. **Funnel re-measured after landing** — and the honest result is that the class *rose*, 19.8% → 29.1% `TARGET_RECONSTRUCTION_UNVERIFIED`, while bind survivors went 51 → 93. That is not a regression: MuPDF materializes wide `TJ` kerns as synthesized spaces (see PITFALLS), so on the dominant document the dict line is *also* a reconstruction, and cases previously mislabeled `NO_MATCH` are now correctly named. **Provenance caveat:** these two figures come from the delegated 2026-08-04 measurement pass; the orchestrator did not independently re-run it and the exact invocation (fixture set + per-page caps) was not captured, so Task 12's ceiling decomposition must **re-measure, not cite**. Original item:
  **Recover the whitespace-collapsed edits (owed; D5 only made them honest, not working).** The verbatim source text *is* available — the dict parse preserves `"Price is  100"` and `"  Hello World  "` exactly (probed 2026-08-01), whereas the rawdict word runs do not. Two blockers before using it: (a) mapping a run's `(block_idx, line_idx)` onto the dict line crosses the rawdict↔dict index-alignment assumption baked into `_build_page_index`, untested at the shapes where it breaks (multi-span lines, blocks `_parse_block` skips, multi-line blocks); (b) it does not help the single-run shape — `"  Total  "` parses to one run `"Total"` that also fails to bind, so leading/trailing padding needs its own answer. **Do this before the measurement pass**, or the pass will read the `TARGET_RECONSTRUCTION_UNVERIFIED` count as a ceiling rather than as a known-fixable gap. *(Update 2026-08-01: the measurement pass ran first anyway, but explicitly deconflated and reported the class as known-fixable — 7,251/36,518 samples (19.8%) after XObject deconfliction — so the feared misreading did not occur. The recovery work is still owed; re-run `scripts/measure_tier_funnel.py` after it lands to watch that 19.8% convert.)*
- [x] **Fix `scripts/audit_tier_coverage.py` predicates (2026-08-01).** `tier1_candidate` no longer requires `capability.face is not None` (contradicted Task 10d — `/Widths` is the contract); both it and `tier0_eligible` now require `tier0_reject_reason is None` **and** the Task 10e glyph proxy `(face is not None or ascii_repertoire_attested)` — a structural audit cannot evaluate text-dependent `missing_glyphs`, and without the proxy the 55 always-refusing capabilities count as headroom. Before/after on the six-PDF corpus: identical (0 / 26 / 38,516) — the proxy costs zero here, verified again post-D1 (`fails_only_glyph_proxy = 0`)
- [x] **Measurement pass (2026-08-01, `scripts/measure_tier_funnel.py`** — counts-only, deterministic, rerun-identical; drives the real resolve stage per the D5 harness, binds against a per-page cached replay cross-checked 0 mismatches vs the real `bind_source_text` over 618 targets, then identity-replacement plan survival). Results (six PDFs + ten synthetic fixtures, 36,518 sampled targets, caps 30 lines/60 runs per page recorded in output; **taken under pre-D1 gates, so funnel rates are now stale relative to production — re-run after any gate change**): (a) bind 0.14% show-weighted vs 18.7% document-weighted (130× divergence — the skew warning was justified); plan 0% everywhere, re-confirming the audit independently. (b) Forward advance-dependency **0.40%** show-weighted, 100% concentrated in `test-complexed-layout.pdf` (6.1% of its own shows; every other file 0%) — Slice 1's kern math is load-bearing for a thin slice of this corpus. (c) Tabular digits: 44.9% of font capabilities but only **5.5% of shows** use such a font — the digit edit class exists but is thin by usage. (d) TJ binding-survival: **0.59%** (146/24,665 kernless) — 99.4% of TJ shows carry kerning and can never byte-bind; feeds the whole-array-TJ pivot condition below. (e) NEW, advisor-driven: `TARGET_IN_FORM_XOBJECT` deconfliction — the production label is page-scoped and only 5.3% of its firings are confirmed target-in-XObject; deconflated `target_reconstruction_unverified` is **19.8% of all samples** (vs 11 raw), squarely the known-fixable gap the item below warned about (see PITFALLS). Shadow telemetry verified, not enabled: collection requires **both** `TEXT_COMMIT_ENGINE=shadow` and `PDF_EDITOR_DEBUG=1` (the INFO log line is dropped at the default WARNING level); `TEXT_COMMIT_TELEMETRY` is parsed but read nowhere (dead flag — wire or remove)
- [x] **Runtime + memory baseline (2026-08-01, `scripts/benchmark_text_commit_baseline.py`** — headless, no Qt; measured numbers live in the **gitignored, machine-local** `benchmarks/baseline-2026-08-01.json` with full p50/p95/p99 — absolute figures deliberately stay out of shared commits). Structure of the result: the real corpus had zero eligible shows pre-D1, so accept-path metrics (commit/verify/undo-redo) come from clearly-labeled synthetic injected fixtures; the reject path — the true per-keystroke driver — was measured on the real dense file. Qualitative shape: accept-path prepare is ~30× the dense reject-path prepare, dominated by the whole-doc scratch copy + `tobytes` reopen; preview pays one whole-doc snapshot at session open, then per-generation work is cheap relative to it; undo/redo via the reversal patchset is ~1000× cheaper than commit (no whole-doc snapshot); teardown leak over 25 cycles is ~20KB tracemalloc (psutil unavailable in the venv — recorded, not faked; stale-generation drop rate is Qt-side and recorded not-measurable-headless). Budgets remain underived per the rollout gate — numbers only. **Repeat after each phase** and after any D1/Slice 1 perf-relevant change
- [x] **D1 — hex-Tj + uniform-scale Tier 0 relaxation (2026-08-01, Red-light first, mutation-verified).** `replay.py`: `_is_translation_only` → `_uniform_scale(m) -> float | None` (factor when `b==c==0, a==d>0`; `None` for rotation/shear/reflection/mirror/degenerate); `ShowOp.trm_translation_only` → `trm_uniform_scale` + derived `trm_uniform_scaled` property. `inspect.py`: bind gates on the property; detail re-worded ("non-uniformly scaled"). `plan.py`: operand gate accepts `string_kind in ("literal","hex")` for `Tj` (`TJ`/`'`/`"` still refused; verified the patch writer already splices the whole operand range incl. `<`/`>` — no writer change); fallback `target_bbox` scale-corrected (Red pinned the exact 2× inflation at `a=d=0.5` — the false-ACCEPT direction, see PITFALLS). The SENSITIVE test was revised into `test_planner_accepts_uniformly_scaled_text_matrix` (same fixture, docstring records the former name); gate coverage moved to two new parametrized rejection tests, mutation-run-verified: `b==c==0` pinned only by `a==d>0`+off-diagonals, `a>0` pinned only by point reflection (see PITFALLS on fixture subsumption). Mirror predicates updated in `audit_tier_coverage.py` + `measure_tier_funnel.py`; one dated plan line. Full suite 2135 passed / 28 skipped / 5 xfailed; ruff + mypy clean. **Audit: tier0_eligible 0 → 5,853 (15.19%) — the prediction held exactly** (`fails_only_glyph_proxy=0`); composition 5,688 hex + 165 literal, **100% at non-unit scale**, so hex-only is worth 0 and the joint-requirement count is 5,688 (the plan's ~5,666 was wrong — corrected, not agreed with). All gain is in `test-large-file.pdf`; the other five files stay at 0 (mc_depth/font gates dominate), which is exactly the D1 pivot-condition scenario below — verified edit-level acceptance outside the dominant PDF is still ~0, so D1 stays opt-in and 15% is headroom, not coverage
- [x] **RESOLVED (2026-08-01/02): scratch-first fingerprint self-check failed on disk-loaded documents — blocked every real Tier 0 accept on the dominant file.** `tobytes(encryption=KEEP)` reorders a disk-loaded object's dictionary keys on first serialization (idempotent after one round trip); `_update_font_dependencies` hashed `xref_object()` strings verbatim, so `TieredCommitEngine.prepare()`'s pre-scratch fingerprint never matched the scratch's — measured on `test_files/test-large-file.pdf`, the exact file where D1 made 5,853 shows eligible. Unit tests never saw it (synthetic fixtures are never disk-loaded). Fixed Red-light-first (`test_scripts/test_text_commit_fingerprint_roundtrip.py`): `_update_font_dependencies` now folds `_canonical_object_digest` — `sorted(xref_get_keys)` + `xref_get_key` per key — instead of the raw `xref_object()` string; order-independent, so the MuPDF reorder no longer moves the digest while a real dependency mutation still does. All 5 genuinely-eligible Tier-0 targets found on this file (pages 13/14/15/18×2) now return `PreparedEdit` from `TieredCommitEngine.prepare()` on the real document. Full suite green, no regressions; see PITFALLS
- [x] **NEW (measurement stage, 2026-08-01 → fixed WS-D 2026-08-03): `TARGET_IN_FORM_XOBJECT` is target-scoped in production `bind_source_text`.** Confirmed via per-target Form XObject replay (one level); a page that merely invokes a logo/bullet XObject no longer rebrands every miss as `TARGET_IN_FORM_XOBJECT`.
- [x] **Codex P2 review fixes (2026-08-01, ultracode workflow, serial opus→haiku→sonnet, each independently re-verified).** Three findings from `/codex:review` on the pre-Task-11 diff: (1) **CONFIRMED, fixed** — the fallback `target_bbox` (D1's scale fix covered only the Tm term) ignores `/UserUnit`: MuPDF folds it into `page.rect`/`page.transformation_matrix` (mediabox stays unscaled), so `binding.origin_page` is page-scaled while `_advance`/`font_size` stay text-space. At `/UserUnit 2` a valid edit was refused (`verification_failed`, halo half-size); at `/UserUnit 0.5` the halo doubled — the dangerous direction, since V0d only proves raster identity *outside* the halo. Fix: `scale = trm_uniform_scale * math.hypot(page_matrix.a, page_matrix.b)` (hypot, not `abs(a)`, which reads 0 at `/Rotate 90`). Red pinned first (2 new tests, both directions), mutation-verified, 4 fallback-bbox tests total incl. an independent MuPDF-rawdict oracle. My own pre-dispatch hypothesis that this was a PyMuPDF false positive was wrong — stated here so the record doesn't quietly bury a wrong guess. (2) **Fixed** — `scripts/measure_tier_funnel.py` printed real PDF basenames in both JSON and text output; replaced with positional `doc_index`, matching the same privacy contract `audit_tier_coverage.py` already documents. (3) **Fixed** — `scripts/benchmark_text_commit_baseline.py`'s `corpus_findings` was a hardcoded pre-D1 string (claimed 0 eligible everywhere); now computed at run time via `audit_tier_coverage.audit_document()`, with the old claim kept inline labeled "Superseded 2026-08-01" for provenance. Scoping check done, not assumed: the real-corpus reject-path benchmark's picked target (densest page of `test-large-file.pdf`) is itself a `TJ`-array element, so its reject reason was already `NOT_SINGLE_LITERAL_TJ` pre-D1 too (a structural gate checked before the text-state gate) — the docstring's old `UNSUPPORTED_TEXT_STATE` claim described `audit_tier_coverage.py`'s *aggregate* classification, not this one `prepare()` call. Full suite re-verified independently: 19/19 structural-gates tests, ruff clean, mypy clean

### During Task 11
- [x] **Slice 1 ships first (2026-08-02)** — transplant + kern compensation (`[(newtext) K] TJ` at the source op's byte range, same font resource/encoding, K absorbs the advance delta, every following show provably unmoved). Landed with all 12 red tests green, full verification suite passing, and six-PDF corpus audit confirming measurable forward-advance dependency is 0.40% show-weighted (99.6% of shows have no consuming successor before the next structural op, so kern compensation is sound and rarely load-bearing). Files completed: `model/text_commit/{dto,plan,patch,verify,inspect,engine}.py`, `model/{pdf_text_edit,edit_commands}.py`, `controller/pdf_controller.py`, `preview.py` threading, undo gate widening, and one test-fixture deviation (char-level vs span-level target_bbox in growth-refusal cases).
- [x] **Tier 1 contracts coverage (2026-08-02)** — extended `Files:` list now includes prepared-candidate token lifecycle in `dto.py:PreparedEdit`, preview↔commit identity in `preview.py`, live-commit rollback gating in `engine.py`, persistence/undo/redo in `edit_commands.py`, resource-dictionary/font-embedding via `patch.build_tier1_font_outcome` + engine pre-scratch/pre-apply honesty re-verification, and shared-content-stream detection via `inspect.find_pages_sharing_content_stream` (both tiers covered, gated in the `_classify_common` prologue). **Deferred:** layout.py, wrapping/alignment/overflow UI, different-face replacement, Identity-H/CID enablement, deletion/multiline, running growth gates inside per-keystroke preview, shadow mode staying Tier-0-only.
- [x] **Operator guard on `patch.py:156-213` (2026-08-02)** — `_SPLICEABLE_SHOW_OPERATORS = {"Tj", "TJ"}`, `_require_spliceable_show(show)` raises `UnsupportedShowOperatorError` at the top of both `build_advance_preserving_erase` and `build_transplant_replacement` (patch.py mechanism), plus policy refusal in `plan.py`'s `_classify_common` before `NOT_SINGLE_LITERAL_TJ` gate (plan.py policy). New `RejectReason.UNSUPPORTED_SHOW_OPERATOR` emitted by both sites, tests confirm ' and " are refused without entering the builders.
- [x] **Halo semantics under growth (2026-08-02)** — decided: blank-growth-zone proof on the PRE-EDIT rendering via two independent gates sharing reason `GROWTH_REGION_NOT_BLANK` but not detail prefix: rawdict character-intersection gate (exact, text-only, size-independent) and raster uniformity gate (covers non-text ink). Widened clip only: `verify_bbox_page = union(target_bbox_page, target box extended along the advance direction by (replacement_advance - source_advance) * trm_uniform_scale)`, with V0c span-origin comparison staying pinned to `target_bbox_page` on both sides (proven pre-edit, never widened). HONESTY LIMITS documented: V0c cannot see merged same-span successors, residual 1.5pt unproven band at the advance edge exists, and V0c's wider clip sees more neighbours (false rejects only, never false accepts).
- [x] **Fallback `target_bbox` uses user-space→visual matrix (WS-D, 2026-08-03)** — build rect in user space, map through `transformation_matrix * rotation_matrix`. PyMuPDF's `transformation_matrix` alone omits `/Rotate`; without `rotation_matrix` a `/Rotate 90/270` halo stays horizontal while pixmap ink runs vertically. `/Rotate 90/270` fixtures + scale/`/UserUnit` controls in `test_text_commit_structural_gates.py`. See PITFALLS.
- [x] **`TEXT_COMMIT_TELEMETRY` wired (WS-D, 2026-08-03)** — shadow measurement `logger.info` emits only when `telemetry == "local"`; default `off` suppresses the line. Classification still runs under `engine=shadow`.
- [x] **D4 — `_ocg_membership_status` tri-state (WS-D, 2026-08-03)** — locked probe + every exception path return `unknown`; `verify_tier1_strategy` records `ocg_membership_unknown`, never `preserved`, on unknown.
- [x] **Stale undo mirrors stale redo (WS-D, 2026-08-03)** — high-fidelity inverse-patch stale → `EditTextResult.STALE_UNDO`, zero mutation, command retained on undo stack; no page-snapshot fallback.
- [ ] **TJ arrays — deferred per pivot condition** — binding survival is 0.59% show-weighted (146 of 24,665 TJ shows are kernless; 99.4% can never byte-bind). Whole-array targets via transplant are sound by construction; in-array splicing with kern rebalancing is rejected. Gate measured 2026-08-01; pivot condition met: "defer if binding survival is negligible" — revisit only if a representative corpus disagrees or binding stops demanding byte equality
- [x] **Same-line successor merges into the target's own rawdict span** (deviation 2026-08-02; PITFALLS cross-ref WS-D 2026-08-03) — char-level `_target_bbox(page, probe)` in Slice 1 growth-refusal fixtures; see `docs/PITFALLS.md` "Same-line successor merges…".
- [x] **WS-B — Tier 1 growth proof + rollback atomicity (2026-08-03, Red-light first, `db5ca5db`):** `growth_outside_page` containment gate at `_build_tier1` (widened verify bbox must sit inside `page.rect`, 1e-3pt tolerance — clamping never substitutes for proof); `prove_growth_region_blank` upgraded from uniformity to background-reference + drawings/images/shading occupancy, fail-closed on every uninspectable path (a uniformly BLACK growth zone is now refused); live-commit `verify_fn` wrapped in try/except → `applied.revert(doc)` + re-raise, so a *raising* verifier can no longer strand a half-applied patch. Tests in `test_scripts/test_text_commit_tier1_slice1.py` (+3, incl. fault injection asserting byte-identical stream + fingerprint after the raise).
- [x] **WS-A — preview↔commit candidate identity (2026-08-03, Red-light first, `ff435fbe`):** token read from the saved `editor` local *before* `view.text_editor = None` (was always `None` at emit); threaded `EditTextRequest.plan_token` → `EditTextCommand` → `model.edit_text(plan_token=)` → `_attempt_tiered_commit`; `TieredCommitEngine` gained the `VerifiedPreparedEdit` cache (`prepare()` auto-caches, FIFO 8, `get_verified_candidate`/`clear_verified_candidates`); `_content_token` preimage widened to full candidate semantics (target/verify bbox, advance pair, kern, font identity, style/geometry intent). Stale cached candidates are refused at apply time by the PatchSet fingerprint gate. New `test_scripts/test_text_commit_candidate_identity.py`.
- [x] **WS-C — preview verdict parity and session candidate identity (2026-08-03, Red-light first):** preview now captures pre-patch state and runs the Tier 0/Tier 1 verifier before rasterizing, refuses growth/blank/outside-page candidates with the live reason class, widens raster clips to `effective_verify_bbox`, forwards style/geometry intent, and returns the verified `PreparedEdit`. `PDFModel` owns one `TieredCommitEngine` per document session; the controller caches that DTO on the GUI thread so commit reuses the preview candidate by `plan_token`. Preview V0e reuses the open session-scratch certificate to preserve the one-scratch-per-session keystroke budget; live commit retains the real KEEP-encrypted reopen probe. New coverage: `test_scripts/test_text_commit_preview_parity.py`.
- [x] ~~**Slice 1 acceptance CLOSED (2026-08-03)**~~ — **SUPERSEDED 2026-08-04 by the entry below.** An adversarial re-verification pass refuted part of this verdict: **P0-3 was not fixed** and P0-1/P0-2 were only partially fixed. The four named residuals listed here are now closed, and one of them turned out to conceal a pre-existing correctness defect. Kept verbatim for provenance; read the 2026-08-04 entry instead. Original text:
  **Slice 1 acceptance CLOSED (2026-08-03, Fable 5 verdict on `task11/slice1-closure`):** all five GPT 5.6 Pro P0s map to commits + red→green tests; during-Task-11 backlog done; gates on the closure HEAD: ruff clean, mypy clean, pytest `2178 passed / 21 skipped / 5 xfailed`. Defaults untouched (`engine=legacy`, `max_tier=0`) — Tier 1 remains flag-off; rollout is Task 12. Named residuals: caller-supplied `target_bbox` shape on `/Rotate 90/270` pages (WS-D fixed only the fallback path); `binding.origin_page` maps through `transformation_matrix` without `rotation_matrix`; `growth_outside_page` reason string not declared as a `RejectReason` constant; View finalize token read has no dedicated GUI assertion. Full amendment in `plans/2026-07-18-acrobat-stable-text-commit-engine-v2.md`.
- [x] **Slice 1 acceptance GENUINELY CLOSED (2026-08-04, `task11/slice1-closure`, Opus-5-orchestrated serial workflows; supersedes the 08-03 entry above).** The 08-03 closure was re-verified adversarially instead of trusted — an independent read-only pass was tasked with *refuting* each of the five P0 fixes on the closure HEAD, and it refuted three of them.
  - **What the re-verification found.** P0-4 (growth outside page) and P0-5 (verifier-exception revert) confirmed fixed and non-vacuous. **P0-3 NOT fixed**: a growth zone painted solid black by a shading inside a Form XObject was still accepted — the occupancy checks are a mechanism blocklist that cannot see into an XObject, and the background-reference gate added alongside them was *inert*, sampling inside the very band it was proving (monkeypatching every occupancy gate to a no-op left all five growth tests green). **P0-1 partial**: the cached-candidate commit path bypassed the style/geometry policy gates, so a drag accompanying an edit was silently discarded (UI-reachable), and the token test was vacuous. **P0-2 partial**: preview's V0e certificate was a tautology (`page_count` compared against itself on the post-patch document) and the Tier 1 font-resource proof was absent from preview.
  - **Fixes (F1–F4, each Red-light first, in the working tree of this commit).** F1 — growth proof rebuilt as a background-*surface* proof (`background_reference_points` disjoint from the widened halo, `_target_background_rgb`'s strict-majority + ink-visibility rule, `_reference_confirms_background`); `_target_tail_reference_rgb` and its fail-open median deleted; occupancy gates demoted to early-outs and the raster proof pinned standing alone with them neutered; `count_growth_zone_glyphs` foreign-overhang blind spot fixed. F2 — cached-candidate branch refuses on `style_overrides.changed` / `new_rect` and falls through to a fresh prepare, re-runs `find_pages_sharing_content_stream` pre-commit, and the controller caches only after the PNG decodes. F3 — `PageState.page_count` captured pre-patch, real per-session KEEP round trip (`_live_keep_round_trip`, one `tobytes` shared by probe and snapshot), `reopen_probe_ok` fail-closed, preview runs `build_tier1_font_outcome`. F4 — live `verify_fn` wrapped in `except BaseException` with revert + re-raise, and a failing revert chains both errors.
  - **The four named residuals are closed, and one hid a real defect.** `RejectReason.GROWTH_OUTSIDE_PAGE` declared (`dto.py:62`), `getattr` fallbacks removed. Rotation parity: `inspect._origin_in_page_space` now composes `rotation_matrix` (Defect A); the caller-supplied `target_bbox` was unconverted dict-space geometry, fixed by `_dict_space_to_visual` at the model boundary (Defect B); **and Defect C, pre-existing and not previously suspected — V0c/V0d compared dict-space rawdict geometry against a visual-space `target_bbox_page`, meaning no tiered commit had *ever* succeeded on a `/Rotate 90/270` page.** Found only because the residual was chased rather than deferred; pinned by `test_full_tiered_commit_succeeds_on_rotated_page[90/270]`. The GUI finalize-token assertion is added and sensitivity-proven by temporarily reintroducing the WS-A bug.
  - **Gates on this tree:** `ruff check .` clean; `mypy model/ utils/` clean (47 files); pytest **2,219 passed / 21 skipped / 5 xfailed / 0 failed**, run **chunked** in four alphabetical parts (402 + 871 + 323 + 623, every chunk exit 0) — a single whole-suite invocation hangs at PySide6 interpreter teardown in this venv, pre-existing and unrelated (see PITFALLS). This is a post-Phase-2 run, deliberately not the Phase 1c number: Phase 2 reshaped `_Tier0Target` and added 365 lines to `pdf_text_edit.py`, and this repo has a recorded pitfall where that class of change breaks `__new__`-built test doubles in a way targeted runs miss. One intermittent flake observed and not reproduced: `test_multi_tab_plan.py::test_05_search_state_restored_per_tab` (green in isolation and on re-run; unrelated tab/search state).
  - **Defaults untouched** — `engine=legacy`, `max_tier=0`, `preview=legacy`, `telemetry=off`. This is acceptance, not rollout.
  - **Still outstanding in Task 11 (not skipped for time — gated by the plan's own rule):** the runtime re-measure against the 2026-08-01 baseline, and Steps 1–6 horizontal Latin layout. The plan's constraint governs: *no layout expansion until Slice 1 preview is responsive*, so the perf gate must run first and layout cannot start ahead of it.

### After Task 11 (Task 12 scope additions)
> **Plan:** `plans/archive/2026-08-12-task12-engine-hardening.md` — evidence-driven P0 reordering (2026-08-12 verification campaign): P0-A replay-chokepoint size guard, P0-B streaming lexer, P0-C staged degrade visibility/consent (promotes T12-P1-06), P0-D CID hex-`Tj` existing-glyph slice. Whole-`TJ` simple demoted to P2 (pivot condition below **triggered**: measured <1% coverage).
- [ ] **Re-measure runtime against the pre-Task-11 baseline** (done 2026-08-01: `scripts/benchmark_text_commit_baseline.py`, numbers in the gitignored local `benchmarks/baseline-2026-08-01.json`). Known risk: `preview.py` re-runs `prepare_tier0_plan` per keystroke generation, replaying every content stream on the page and then re-reading them (`inspect.py:213-217`, `plan.py:228-229`) — a full page re-parse per keystroke on the 35,844-show file. If dense-page preview p95 regresses: cache replay/index state, eliminate the duplicate stream read, debounce or tile raster work — and do **not** expand into paragraph layout until Slice 1 is responsive
  - 2026-08-12 (Task 12 P0-A/P0-B landed): the OOM half is closed — peak RSS on a dense-page prepare is now flat (~45–75 MB; was ~133× the stream size), and pages over the 4 MiB summed budget refuse in ~15 ms with `content_stream_too_large_for_safe_replay` (legacy fallback, which never lexes). The **latency half stays open**: prepare still costs ~1.05 s per MiB of decoded stream per keystroke (measured 0.5/2/3.8 MiB → 0.53/2.1/4.1 s), so replay/index caching + duplicate-read elimination remain the fix for dense-page preview responsiveness
- [ ] **Publish coverage as a funnel, both weightings** (GPT-5.6-sol): selected edits → target resolved → source bound → encoding/glyph accepted → candidate built → preview verified → commit verified → save/reopen verified. Report per document class, and give **document-weighted alongside show-weighted** numbers so the 35,844-show file cannot define the headline. Structural eligibility is headroom, never product coverage
- [ ] **Zero-tolerance correctness gates — any one blocks rollout:** mutation after a stale/rejected prepare; changed non-target stream bytes; moved following text; changed font/resource binding without a declared outcome; raster difference outside the declared affected region; preview candidate ≠ committed candidate; a "preserved" result where verification was not evaluable; failed undo/redo/encryption/save-reopen matrix
- [ ] **Pivot conditions, agreed in advance:** D1 — if verified edit-level acceptance stays near zero outside the dominant PDF, keep it opt-in and stop quoting 15% as coverage. Slice 1 — if the composite cannot preserve following origins and outside-region pixels, stop Tier 1 transplant rather than weakening verification. Whole-array `TJ` — defer if binding survival is negligible. Paragraph layout — narrow scope rather than silently degrading fidelity if it needs ambiguous multi-show reconstruction or uncontrolled resource mutation
- [ ] **Report the Q3 ceiling decomposed, not blended:** Task 11's real ceiling is materially below the 72.79% structural figure — Identity-H stays NO-GO so `font_unsupported_encoding` (14.74%) never clears; `render_mode` (5.55%) is unaddressed by Task 11 scope; `mc_depth` (6.51%) plausibly clears via transplant inheritance. Nothing currently computes the actual ceiling; the rollout decision needs it
- [x] Task 12 as planned — **sealed 2026-08-14** (plan archived to `plans/archive/2026-08-12-task12-engine-hardening.md`; P0-A/B via PR #28, P0-C Phase 1/2 via PRs #29/#30, P0-D via PR #31, Step 7–8 cleanup via PR #32). Rollout gates remain OPEN by design: defaults are still `legacy`/`max_tier=0`, and the three corpus blockers (marked-content tolerance, rotated-Tm, replay-budget latency) move to `plans/archive/task13-cad-binding-unlock.md` — nothing reaches a user until those gates pass

#### Task 12 named P1 defects (GPT 5.6 Pro review — register only; do not implement in Task 11)
Registered 2026-08-03 (WS-D). Each needs a red fixture before work starts:

| ID | Defect | Suggested fixture name |
|----|--------|------------------------|
| T12-P1-01 | `gs`/ExtGState font-state ignored by replay | `test_replay_tracks_extgstate_font_ops` |
| T12-P1-02 | Font registry owner identity collapses to resource-name-only | `test_font_registry_distinguishes_owner_xref` |
| T12-P1-03 | Target tofu / wrong-glyph not proven (extraction ≠ glyph outline) | `test_verify_rejects_tofu_replacement_glyph` |
| T12-P1-04 | Fingerprint dependency graph incomplete (FontFile/ExtGState/OCG/geometry/AP) | `test_page_fingerprint_covers_fontfile_extgstate_ocg_ap` |
| T12-P1-05 | Non-page stream aliasing (Form/Pattern/annot AP sharing target stream) | `test_bind_refuses_shared_form_or_ap_stream` |
| T12-P1-06 | Non-strict silent legacy fallback consent UX | ~~`test_non_strict_legacy_fallback_requires_consent`~~ **RESOLVED 2026-08-12** (P0-C phase 1 visibility + phase 2 consent, see below) |

- 2026-08-12 (Task 12 P0-C phase 1): T12-P1-06's **visibility half landed** — a
  `degraded_committed` edit now surfaces exactly one warning notice carrying the
  `fallback_chain` reason codes (incl. the P0-A guard reason verbatim), with the
  plain success toast suppressed for that edit (`test_text_commit_degrade_visibility.py`,
  13 tests after same-day adversarial verification: default-engine
  over-notification, commit-stage detail leak, cross-page-move silent gap, and
  stale-flag leak into add-textbox were all found and fixed red-first). The
  semantic fidelity gate landed as an acceptance-only harness
  (`test_scripts/semantic_fidelity_gate.py` + 7 tests) pinning the
  `outside_diff == 0` false negative; runtime enforcement is still an open plan
  §9 question. **Known, accepted gate scope limits** (low severity, documented
  in the module docstring — widen before judging real mixed-style or
  graphical-occlusion commits): the gate is extraction-based and blind to
  non-text occlusion (an opaque fill/image over a neighbor survives
  undetected); a mixed-style target region (two fonts in one edit's bbox) is
  judged only against its first character's style.
- 2026-08-12 (Task 12 P0-C phase 2): **T12-P1-06's consent half landed —
  item CLOSED.** A real tiered→legacy fallback now pauses before the legacy
  mutation via a Qt-free callback injected into `model.edit_text()`
  (`confirm_fallback`); a decline is zero-mutation
  (`EditTextResult.FALLBACK_DECLINED`), a confirm proceeds exactly as before
  Phase 2 existed (`test_text_commit_consent_flow.py`, 13 tests after
  same-day adversarial verification: a redo-reprompt-bypass bug where a
  command that won cleanly at Tier 0 could silently arm a future redo to
  skip asking, found and fixed red-first). Session-level "always allow" is
  explicitly deferred, not started. **Known, deterministic UX consequence**
  (not a bug, explicitly reviewed and endorsed): under the tiered engine,
  cross-page move's source deletion always uses an empty replacement,
  which always rejects at the Tier 0 prepare stage — so every cross-page
  move prompts for consent once the tiered engine is enabled, every time.
- 2026-08-12 (Task 12 P0-C phase 2, post-review fix — **RESOLVED**, was
  registered below as out-of-scope, promoted to a PR #30 merge blocker):
  the mode-switch success toast gated only on `TextEditFinalizeResult.
  outcome == COMMITTED` (signal emitted without raising), never the
  Controller's actual `EditTextResult` — so a user who explicitly declined
  the new consent prompt (zero mutation, no undo entry) could still see
  "文字已儲存" on the next mode switch. Fixed with
  `PDFController.consume_last_edit_result()` (pull-and-clear, mirrors
  `consume_last_edit_degraded()`); `set_mode()` now requires a pulled
  `EditTextResult.SUCCESS` before the toast can fire at all. Also closes
  the same pre-existing gap for `REJECTED_STRICT`/`TARGET_BLOCK_NOT_FOUND`.
  5 new tests (4 requested + 1 production-View-method red mirroring Phase
  1's F6 discipline) + 1 existing pin updated to assert a genuine second
  edit instead of stale mock state. Adversarial verification (workflow
  `wf_1f9461b8-4cd`) then caught 2 more (high + medium): the new
  `_last_edit_result` reset in `move_text_across_pages`/`add_textbox` was
  placed after, not before, each method's own early-return validation
  guards, so a stale `SUCCESS` from an earlier unconsumed edit could
  survive a later, unrelated interaction's guard failure. Fixed by moving
  both resets to each method's true first line; 2 more regression tests
  added.
- 2026-08-13 (Task 12 P0-D steps 1–4 — census, scope lock, fixtures, RED):
  Type0 encoding census landed (`scripts/audit_type0_census.py`, read-only,
  aggregate-only): private corpus is **100% Identity-H + CIDFontType2 +
  Identity CIDToGIDMap + readable /W + embedded** (262/262 fonts; ToUnicode
  260/262 structurally parseable — 2 use array-destination bfranges and
  fail closed under `type0_tounicode_unparseable` in v1) — v1 scope locked
  unchanged in plan §8; the §9 CMap-scope open question is RESOLVED.
  Census also surfaced the corpus-dominant INLINE `/DescendantFonts
  [<<...>>]` form (256/262, AutoCAD) that `collect_cid_encoding_evidence`
  currently rejects — implementation must handle it (see PITFALLS).
  Synthetic fixture builder (`test_scripts/type0_fixture_builder.py`) +
  red matrix (`test_scripts/test_text_commit_cid_hex_tj.py`) landed, then
  were adversarially hardened (workflow `wf_a084d864-566`, 7/7 findings
  confirmed and fixed red-first — incl. the census correction above, which
  the round's structural-validation finding forced): final state **38
  tests — 35 red / 2 fixture-sanity / 1 replay-budget pin**, every red
  failing on the pre-P0-D `undecodable_target` binding refusal. The
  `type0_*` per-gate reason codes in the test module ARE the P0-D
  contract. This partially
  addresses the Q3-ceiling item below (Identity-H NO-GO is exactly what
  P0-D lifts).
- 2026-08-13 (Task 12 P0-D steps 5–7 — implementation GREEN): after the
  user's go-ahead + 5 more red pins (explicit /Identity name, scalar
  bfrange positive, 3 more STALE_PLAN staleness pins), the CID codec
  landed: new leaf `model/text_commit/cid_fonts.py`, Type0 capabilities in
  `fonts.py` (no face; per-lookup evidence-digest revalidation),
  registry-driven Type0 binding leg + full Type0 fingerprint closure in
  `inspect.py`, per-capability planner branch with hex operand
  serialization in `plan.py`/`patch.py`/`pdf_lexer.py`, legacy
  `_parse_tounicode` fabrication fixed + inline-descendant support in
  `verify.py`. **All 43 P0-D tests green on the first run**; full suite
  2319 passed / 0 failed; ruff/mypy/import-linter clean; 3 obsolete
  Type0 pins updated (helv TextWriter → CIDFontType0 descendant, see
  PITFALLS). Acceptance funnel (`scripts/measure_type0_funnel.py`,
  aggregate-only) reported HONESTLY: 0 source-bindable shows on the
  reference corpus today — 59% of Type0 shows behind the P0-A budget
  (intact by design), 100% of the budget-eligible remainder inside
  BDC/EMC layer wrappers (`mc_depth`), 95% on rotated text matrices —
  all outside P0-D's locked scope; registered as the mc_depth/rotated-Tm
  P1 follow-ups + the §9 budget-relaxation item. The Q3-ceiling item
  below now has REAL per-condition decomposition data from the funnel.
  Rollout defaults unchanged (legacy, max_tier=0).
- 2026-08-13 (Task 12 P0-D pre-PR review round — `wf_1757a5fb-8e9`,
  plan-code-reviewer + skeptical verifier, verdict ship-with-fixes): 2
  confirmed findings fixed red-first — (1) BLOCKING: the hybrid
  indirect-array-holding-inline-descendant form was accepted by the
  capability builder but invisible to the fingerprint's canonical
  descendant fold → prepare→mutate→commit COMMITTED instead of
  STALE_PLAN; fold now keys on the resolved dict, not the arrival path.
  (2) MINOR: literal-string Identity-H `Tj` silently widened the locked
  hex-only scope; the CID plan branch now refuses non-hex operands
  (`not_single_literal_tj`) and the funnel stage is `single_hex_tj`.
  Matrix 52/52; full suite 2328/21/5/0; review follow-ups registered in
  plan §8 (perf indexes, XObject name-shadowing [pre-existing],
  cached-rejection revalidation, literal-escape canonicalization,
  odd-length code attribution, composite-component walk, ttcf offsets).
- 2026-08-14 (Task 12 sealed — Step 7–8 closure): PR #31 merged into
  `task11/slice1-closure` as a true merge commit (`d961342`, red-first
  history preserved). Step 7: `CommitOutcome.decision_chain` records the
  tier decision trail on successful tiered commits (`fallback_chain`
  stays `()` — reserved for true degrades; no by-fable port, no
  `strategy` field until a second Tier 1 strategy exists); the dead
  Track A/B reflow hook was removed after the red pin CAPTURED its
  per-edit warning + spurious status-bar override from the production
  wiring (evidence grade upgraded from agent-reported). Step 8: final
  anonymized staged funnel recorded in the archived plan §8 (the seven
  user-specified survival stages — structural family, ToUnicode-
  acceptable, replay-budget, marked-content, rotated-Tm, source-
  bindable, replacement-encodable — plus the base show counts;
  marked-content and uniform-Tm survival are now explicit funnel
  stages); PITFALLS +1 (dead-hook entry, index 264); plan `git mv`-ed
  to `plans/archive/`. Corpus-unlock follow-ups live in
  `plans/archive/task13-cad-binding-unlock.md`.
- 2026-08-14 (Task 13 step 1 — wrapper-taxonomy census, read-only,
  aggregate-only): replay now captures marked-content wrapper EVIDENCE
  (`McWrapper` table + `ShowOp.mc_stack`, `mc_depth` semantics frozen,
  BDC/BMC oddities never set malformed); taxonomy classifier lives in
  `scripts/wrapper_taxonomy.py` (census-before-code — no admission logic
  in model); funnel gained the `mc_census` aggregate block with a
  data-policy pin test (no document strings in the report). 31-test
  red-first matrix; Codex review round fixed 2 findings red-first
  (exact-shape BDC/BMC operand parsing fail-closed; bare
  `true`/`false`/`null` retained as operands). Corpus result: of the
  10,701 mc-gated shows, **64.2% sit under pure default-visible `/OC`
  layers (admissible)**, 35.8% in the v1 `malformed_pairing` bucket; no
  nesting (depth 1 everywhere), zero semantic wrappers; only 376
  admissible shows also have uniform `Tm` + default state — Priority 2
  (rotated `Tm`) stays the bulk unlock. Recorded in the Task 13 plan §7;
  base funnel stages re-verified byte-identical to the sealed record.
- 2026-08-14 (Task 13 steps 2+3 — Priority 1 marked-content admission):
  the blanket mc gate became a fail-closed taxonomy admission
  (`model/text_commit/marked_content.py`, promoted from the census
  classifier): only default-visible pure `/OC` layer stacks admit, four
  new stable `MC_*` reject codes, splice boundary guard on new
  `McWrapper` byte spans, and the page fingerprint folds the wrapper
  evidence closure (visibility flip / properties re-point / OCG mutation
  between prepare and commit all go STALE_PLAN). 28-test red-first
  matrix (5 proof obligations pinned). Key discovery: PyMuPDF
  `get_ocgs`/rendering are a LOAD-TIME snapshot — `/OCProperties` writes
  don't refresh them; admission + fingerprint parse the SERIALIZED
  catalog instead (PITFALLS, index 266). Step-3 funnel:
  `outside_marked_content` 0 → **6,872** (census-exact), **376 shows now
  clear every plan gate** (was 0), corpus e2e sample 8/8 committed with
  reopen-extraction OK; bottleneck moves to Priority 2 rotated-Tm
  (6,444 `state:trm_not_uniform_scaled`). Adversarial round (Codex +
  serial deep-reasoner workflow) fixed 4 admits-unprovable findings
  red-first: `/D /AS` auto-states (AS-selected OCG → unprovable),
  fail-open `/BaseState` (now deref'd, exactly `/ON`/`/OFF`),
  parse-budget fold asymmetry (structured-surface fold), duplicate
  dict keys (shared parser refuses). 9 more red pins; corpus numbers
  re-verified identical after all fixes.
- 2026-08-19 (Task 13 step 4 census-before-code — rotated-TRM census,
  read-only, aggregate-only): matrix taxonomy of the 6,444 post-P1
  TRM-gate deaths (`scripts/trm_taxonomy.py` classifier — user-space
  shape of `Tm × CTM` + visual baseline direction through
  `transformation_matrix × rotation_matrix`; funnel `trm_census` block;
  70-test red-first matrix). Corpus: **6,417/6,444 uniform rotations;
  6,413/6,417 of those (99.94%) are visual quarter-turn (`right` 6,212;
  6,413/6,444 = 99.52% of all TRM-gate deaths), all on `/Rotate 270` pages, all
  P1-admitted wrapped shows; zero near-miss rounded matrices; predicted
  newly bindable 5,558 (quarter-turn) vs 5,561 (any-uniform — +3
  only)**. v1 scope LOCKED to the quarter-turn family; acceptance for
  the P2 implementation = census prediction exactly (6,413 gate /
  5,558 downstream). Adversarial round (serial 2-agent Attack→Verify)
  fixed 3 findings red-first: `near_miss` diagnostic (rounded quarter
  turns), `ABS_SCALE_FLOOR` in front of the predicted chain (mirrors
  replay's absolute `_EPS` floor), dual-scope predicted counters;
  `/Rotate` folded to a closed 0/90/180/270/`other` vocabulary. Fixture
  pitfall: PDF numbers have no exponent notation — `%g` writing
  `6.12e-17` silently voids the whole `Tm` under a real lexer. Next:
  P2-B red matrix (stable `trm_*` codes, rotated kern axis, directional
  growth proof, page-geometry staleness pins) — plan §7 step-4 record.
- 2026-08-20 (Task 13 step 4 P2-B — rotated-TRM admission red matrix,
  tests only): four new files (`test_text_commit_trm_admission` 44 red /
  1 control, `_trm_tier1_kern` 12 red / 1 control,
  `_trm_growth_directions` 32 red, `_trm_page_geometry` 7 red /
  3 controls — **95 red confirmed before any implementation**) pin SEVEN
  literal `trm_*` codes with fixed gate precedence (absolute
  `trm_scale_below_floor` promoted to its own code), relative-tolerance
  boundaries at three scales, the full /Rotate × quarter-turn-Tm visual
  direction truth table, the new `model/text_commit/transforms.py`
  contract (census `scripts/trm_taxonomy.py` must delegate; no-drift
  probe grid), rotation-invariant text-space kern with successor-origin
  preservation in both visual coordinates (kern-gap `[-2000] TJ`
  fixture), four-direction growth gates through one shared
  `growth_direction`, and prepare→mutate /Rotate //UserUnit/CropBox/
  MediaBox (incl. raw-xref and page-tree-inherited) → `STALE_PLAN` pins.
  Contract details in plan §7. Next: quarter-turn admission
  implementation; acceptance = census prediction exactly (6,413 gate /
  5,558 downstream, SET identity not just counts).
- 2026-08-20 (Task 13 step 4 P2 — quarter-turn admission
  IMPLEMENTATION): red matrix 95→green (104/104 incl. 4 new F3
  invariant pins); NEW `model/text_commit/transforms.py` single source
  (census `scripts/trm_taxonomy.py` delegates); binding gate =
  `admission_verdict` with seven `trm_*` codes; plan geometry rides
  `map_text_quad_to_visual` + directional `_grown_verify_bbox` +
  `PreparedEdit.growth_direction`; verify growth gates direction-aware
  with dict-space conversion (PITFALLS 269: `get_drawings`/
  `get_image_rects` speak UNROTATED page space); fingerprint folds
  resolved page geometry + live visual matrices; funnel gate mirrors
  production with per-code `state:trm_*` slugs + SET-identity
  acceptance block. Replaced-contract pins updated (structural gates,
  replay, audit, census funnel test). Full per-file sweep green.
  Registered follow-up: `scripts/measure_tier_funnel.py` (legacy
  simple-font tier funnel) still models the OLD blanket TRM gate —
  update when that funnel is next used.
- 2026-08-20 (Task 13 step 4 P2 — implementation review round,
  wf_3cb287ec Attack + hand verification after the Verify agent hit the
  session limit): 5 findings — F2 CONFIRMED fixed red-first (admission
  gate now skips replay-uniform shows except `trm_non_finite`, keeping
  the pre-P2 admitted boundary sliver admitted and re-aligning
  funnel↔production); F4 CONFIRMED fixed red-first (fingerprint folds
  numeric `/UserUnit` canonically — MuPDF re-prints integer-valued
  reals as ints, PITFALLS 270); F1 documented (funnel acceptance sets
  are one-directional predicted ⊆ production — fail-loud only); F3
  accepted as documented (~1 ulp axis-path drift, fail-closed); F5
  docstrings corrected (verify re-derives the growth edge; slug is
  token-bound, not threaded). Details in plan §7.
- 2026-08-20 (Task 13 step 5 — funnel acceptance, corpus, --no-e2e):
  SET-identity acceptance PASS at the sealed tip — gate 6,413
  predicted == 6,413 production, downstream 5,558 == 5,558, both
  symmetric differences 0, membership exact; census counters identical
  to the pre-implementation baseline; blanket slug decomposes exactly
  (6,444 = 6,413 admitted + 27 reflected + 4 not-quarter-turn).
  Corpus e2e pass deferred (optional per step-4 advisory — ride the
  rollout-gate work). P2 slice ready for its PR (base
  task11/slice1-closure) — do not push/open until instructed.
  **P2 MERGED 2026-08-20**: PR #34 → `task11/slice1-closure` @ 137a50b,
  all 9 CI checks green, 6 commits preserved unsquashed.
- 2026-08-21 (Task 13 step 6 first half — P3-A replay-index spike,
  branch `task13/p3-replay-indexing`, read-only, zero `model/` change):
  serial analysis round (invalidation census: pull-validation is the
  contract — four mutation classes have NO push signal; checkpoint
  contract: Shape B is necessarily a hybrid), 41-test red matrix +
  two spike prototypes + latency harness (`scripts/replay_index_spike
  .py`, `scripts/benchmark_replay_index_spike.py`), serial
  Attack→Verify review (8 findings, 4 important, all fixed — three
  were measurement-integrity defects gating the census run), corpus
  measurement DONE: **replay is ~90% of the 2.7–4.8 s per-keystroke
  cost on dense pages; honest validated warm lookups are 8–14 ms
  (page-paired prototype-lookup comparison ~310×–430×, standalone spike
  path with pull-validation included, excludes plan/verify/apply/
  render, not a production speedup — see plan §7 post-PR audit
  correction); Shape A (materialized ShowOp table) wins — Shape B
  (sparse checkpoints) REJECTED for v1 on measured memory (3.3×–6.1×
  Shape A's total retained, page-paired).**  4 MiB budget untouched; no
  persistent cache.  Scope verdict + P3-B follow-up order in
  `plans/archive/task13-p3a-replay-index-spike.md` §7.  **PR #35 opened
  2026-08-22** against `task11/slice1-closure`; a 2026-08-22
  post-PR-audit docs-only reconciliation commit corrected the numbers
  above — see plan §7's "Post-PR claim audit correction" record for
  the full derivation. This partially
  addresses the "latency half stays open" item above: the fix is now
  measured and shaped (reuse one replay across bind→plan, then the
  per-generation Shape A table), but nothing lands in production until
  the P3-B slice.

- 2026-08-22 (Task 13 step 6 second half — **P3-B production replay
  reuse, COMPLETE**, branch `task13/p3b-replay-evidence-plumbing` cut
  from the post-PR-#35 closure merge `e71b13e`): one complete bounded
  slice — evidence seam (`model/text_commit/evidence.py`; one coherent
  stream read per prepare feeding bind + stream selection + the
  fingerprint's stream portion), retained Shape A (`ReplayEvidence`
  wraps the production `PageReplay` verbatim), lookup-time
  pull-validation (fresh read + sha256 digest compare before any reuse;
  refused/malformed/unbounded replays can never become evidence),
  renderer-owned single-slot `ReplayEvidenceCache` (engine.prepare stays
  ephemeral), 40-test red-first matrix, serial Attack->Verify review
  (4 findings R1-R4, top 3 independently CONFIRMED, all fixed), and a
  replay-count acceptance harness (`scripts/benchmark_p3b_preview_reuse
  .py`): cold = 1 replay, 30 warm keystrokes = 0 replays (30/30
  validated hits), unsignalled mutations rebuild every time, false
  hits = 0, memory bounded (entry_count pinned at 1, close releases).
  Measured on the synthetic dense page: cold prepare 11.9 s vs warm
  validated prepare p50 31 ms; warm end-to-end render p50 ~3.3 s with
  zero replays — the residual splice/verify/raster share is the next
  P3 lever, explicitly NOT claimed solved. Fences held: 4 MiB budget
  untouched, no admission widening, no persistent/document-wide cache,
  rollout defaults unchanged. Record: `plans/archive/task13-p3b-replay-reuse.md`.
  **Follow-up (from review R1, pre-existing, NOT a P3-B regression):**
  `DocumentFontRegistry` serves cached simple-font capabilities without
  per-lookup revalidation until `bump_generation` (Type0 already
  digest-revalidates) — extend the Type0-style evidence-digest check to
  simple-font cache hits on the engine path; see PITFALLS "Simple-font
  capabilities are served stale within a registry generation".
  **→ CLOSED 2026-08-27** by the Task 13 revalidation slice (entry below).

- [x] 2026-08-27 (Task 13 — **simple-font capability pull-revalidation,
  COMPLETE**, branch `task13/simple-font-capability-revalidation` cut from
  `task11/slice1-closure@0578866`; sequenced BEFORE P3-D so the known
  correctness hole is sealed before the interpretation pipeline moves):
  every `FontCapability` now carries a same-document `evidence_digest`
  (`compare=False`); `compute_font_evidence_digest` dispatches on the
  `get_fonts` entry's subtype (Type0 → `compute_cid_evidence_digest`, else
  the new `compute_simple_font_evidence_digest`: font-dict keys, indirect
  `/Encoding`/`/Widths`/`/FirstChar`/`/LastChar`/`/FontDescriptor`
  targets, `FontDescriptor/Flags`, raw `FontFile*` bytes; inline xref-0
  dict → constant); `page_capabilities` re-derives it on EVERY lookup
  before the cache probe and rebuilds on mismatch, digest taken BEFORE the
  build. Subtype dispatch also closes the same-class hole for a REJECTED
  Type0 (`cid is None`). Red-light first: 19/21 Red in
  `test_scripts/test_text_commit_font_revalidation.py`, then Green.
  Ultracode refute-first review (3 lenses, 2 important findings both
  CONFIRMED by independent probes and fixed pre-commit, each Red-first):
  F1 — the digest must also fold the MuPDF-RESOLVED `get_fonts` entry
  fields (ext/subtype/basefont/encoding), or an indirect `/BaseFont`,
  `/Subtype` or `/BaseEncoding` target rewrite serves stale (Helvetica face
  served for a font renamed to Wingdings); F2 — `capability(page, name)`
  routed through the whole-page map, O(K·N) digests per prepare (98-font
  page 1.45 s → 10.3 s); now resolves the single matching entry (98-font
  page 340 ms, small pages within noise). Minor closed: `FontFile*` stream
  dict folded alongside raw bytes (`/Filter` rewrite). Final: 27 tests in
  the new file, 147 Green across fonts/widths/cid/replay suites, full
  suite green. Fenced OUT: P3-D DL/TP reuse, `fitz.TOOLS` flag governance,
  dense-CJK growth admission, rollout. Record:
  `plans/archive/task13-simple-font-capability-revalidation.md`.
  **Follow-up correction (2026-08-27, characterization guard-pins):** the
  originally recorded `inspect._update_font_dependencies` analogous gap is
  REFUTED. `page_fingerprint()` has folded the complete MuPDF-resolved
  `get_fonts(full=True)` entry since its initial implementation, before its
  separate object-dependency closure. Three Green-from-first-run pins cover
  indirect `/BaseFont`, `/Subtype`, and inline `/BaseEncoding` target
  rewrites: the live fingerprint is KEEP-round-trip stable before mutation,
  then changes and forces `commit == STALE_PLAN` with zero stream mutation.
  These are characterization guards, not a red-first production fix.
  **→ CLOSED 2026-08-27** by
  `task13/cid-stream-evidence-attestation`: `compute_cid_evidence_digest`
  now folds the builder-visible decoded bytes returned by the same
  `_stream_bytes()` helper the CID builder uses for `FontFile2`,
  `CIDToGIDMap`, and `ToUnicode`. Six red pins cover direct and indirect
  `/Filter` target rewrites with byte-identical raw storage; unreadable
  post-mutation evidence rebuilds to a stable fail-closed rejection. An
  unchanged control reuses the identical capability, and a structural
  performance guard permits exactly one decoded read per evidence stream
  on a warm single-resource hit. Probe p50: 0.011 ms ToUnicode, 0.135 ms
  CIDToGIDMap, 3.617 ms FontFile2; no raw+decoded double hashing.

- 2026-08-23 (Task 13 step 6 third pass — **P3-C preview post-prepare
  latency, COMPLETE**, branch `task13/p3c-preview-postprepare-latency`
  cut from the post-PR-#36 closure merge `f57f590`): the P3-B-named
  residual lever, one complete census->implementation->acceptance
  slice. Census phase-attributed warm `PlanPreviewRenderer.render()`
  on the dense synthetic page: `apply_patchset` (38.7%) +
  `AppliedPatch.revert` (36.8%) = 75.5% of render time, each exactly
  one `Document.update_stream()` call on the ~2.5 MiB content stream;
  root-caused to FlateDecode compression (`compress=1` default, ~540x
  cost vs `compress=0` on an isolated 2.6 MiB stream). Fix: both
  gained a `compress: bool = True` keyword (default preserves every
  existing caller); `PlanPreviewRenderer` alone passes `False` at both
  call sites, since its scratch is never saved or `tobytes()`'d — the
  live commit path (`TieredCommitEngine.commit`) is untouched. 16-test
  red-first matrix, deep-reasoner adversarial review (6 findings
  F1-F6, all independently re-verified, all fixed), and a
  compress-count acceptance harness
  (`scripts/benchmark_p3c_postprepare_latency.py`): every preview
  keystroke = 0 compressed / 2 uncompressed `update_stream` calls,
  live commit keeps its existing >=1 compressed / 0 uncompressed calls
  unchanged (regression guard), memory bounded structurally (stored
  representation size identical across 100 keystrokes — NOT
  `tracemalloc`, which is blind to PyMuPDF's C-side storage, see
  PITFALLS). Measured: warm render p50 874 ms -> 267 ms (~3.3x) on the
  same dense corpus; cold render (replay-dominated) 5.2 s. Fences
  held: no admission/budget/plan-semantics/rollout-default change,
  live document write path untouched. Record:
  `plans/archive/task13-p3c-preview-postprepare-latency.md`. **Named next
  lever (not solved here):** three `page.get_pixmap()` calls + six
  `page.get_fonts(full=True)` scans per keystroke (`capture_page_state`
  + `verify` + the final preview raster), ~92% of the post-fix total.

- 2026-08-23 (**P3-C bridge round, COMPLETE** — same branch, 4 more
  commits `4012114`..`docs`): closed the gaps between the shipped slice
  and the fuller P3-C spec. (1) Extended matrix 16->29 tests: the
  compress flag proven observationally invisible through the REAL
  `render()` for Tier 1 kern+growth, Type0/CID Tier 0/1, visible /OC,
  rotated quarter-turn Tm; plus the suite's FIRST forced V0a-V0d
  verification failures (previously only positively pinned) and
  preview-path injected-failure/raising-verifier revert pins — all
  under `compress=False`, each control leg proving its monkeypatch
  engaged. (2) Committed dual-mode stage census
  (`scripts/benchmark_p3c_stage_census.py`): same-process old-vs-new
  per-stage p50/p95, full primitive counter table, small-page control
  (no reproducible regression), replay contract re-asserted
  (cold=1/warm=0), token identity between modes, working-set snapshots;
  dense warm p50 2,715.8->538.4 ms same-process (5.04x vs predicted
  4.75x — ratio reproduced, absolutes drift with machine state,
  vindicating counts-not-milliseconds). (3) Complete per-file pytest
  sweep at `3c502b4`: 227 files, 0 FAIL. (4) Second adversarial round
  (workflow attack -> skeptical verify, serial): 6 findings B-F1..B-F6
  all CONFIRMED and fixed (control-leg engagement asserts + mutation-red
  proof; plan-record overclaims corrected; nearest-rank p95; machine-
  neutral wording). **Next-lever REFINED by the census:** six
  independent content-stream interpretations per keystroke (3
  DisplayList + 3 TextPage builds inside PyMuPDF's own
  `get_pixmap`/`get_text`, ~99 ms each, none reused — `get_fonts` is
  latency-trivial at ~1.5 ms total, correcting the earlier framing);
  the one-post-patch-DisplayList+TextPage reuse design is the P3-D
  candidate (plan §6c/§8). **Still OPEN from the spec:** the private
  real-PDF corpus census leg (requires a locally provided corpus,
  absent by default) and repo-wide `ruff format --check` (fails on 302
  pre-existing files incl. pre-P3-C ones; the enforced gate is `ruff
  check`, which is clean). `lint-imports` verified 4/4 KEPT locally.

- 2026-08-25 (**P3-C PR #37 CI follow-up, fixed** — same branch, one
  more commit): the single-process CI suite failed
  `test_preview_render_type0_cid_tier1_identical_and_uncompressed`
  (`growth_region_not_blank`) on both platforms (Windows blocking,
  Ubuntu advisory) while every isolated and per-file run was green.
  Proven root cause, not a compress regression: `PDFModel.__init__`
  sets the process-global `fitz.TOOLS.set_small_glyph_heights(True)` in
  the first collected test
  (`test_1pdf_horizontal.py::test_horizontal_edit_and_verify`), the
  caller-supplied text-extraction bbox (the app's own path) becomes a
  fontsize-tall 0.8/-0.2 em box in which the dense-CJK target has no
  strict-majority background colour, and the Tier 1 growth proof
  rejects the `+1 em` candidate identically under `compress=False` and
  forced `compress=True` (a gate on the PageState captured before
  apply, so no compressed byte can influence it). Fix: the Type0/CID Tier 1 pin now uses `REPLACEMENT_SHORTER`
  (Tier 1, `has_ink_growth is False` asserted); growth parity stays on
  the simple-font Tier 1 pin. Production growth proof untouched;
  PITFALLS entry added. **New follow-ups (neither P3-C nor P3-D):**
  (a) suite hygiene — **closed by GATE16-1 (2026-10-12):** `conftest.py`
  pins the production flags (small glyph heights on, quad corrections
  on) at import and around every test, the state CI's single-process
  suite already ran almost every test under; (b) admission gap — under the app's own
  `set_small_glyph_heights(True)`, Tier 1 growth candidates whose
  non-background pixels (ink plus anti-aliased fringe) reach ≥ 50 % of
  the fontsize-tall 0.8/-0.2 em extraction bbox (dense CJK) are
  fail-closed rejected by `_target_background_rgb` on BOTH app paths
  (preview `pdf_controller.py` and commit `pdf_text_edit.py` pass
  `target_bbox=target.bbox`), while `target_bbox=None` callers are
  admitted through plan.py's flag-immune 1.35 em metric quad (why the
  `test_text_commit_trm_*` growth tests stayed green in the same run);
  smallest candidate remedy: sample the majority colour over the
  planner's metric-quad height (or the halo ring) instead of the
  extraction bbox, behind a corpus-backed red matrix.

- 2026-08-28 (Task 13 step 6 fourth pass — **P3-D interpretation reuse,
  COMPLETE**, branch `task13/p3d-interpretation-reuse`): introduced a
  mutation-window-scoped `PageInterpretation` and a renderer-owned one-slot
  `PreStateBaselineCache`. Final hard counts reduced the legacy six page
  interpretations to Stage-A 3/4, Stage-B cold 2/4, and Stage-B warm 1/2
  (unrotated/rotated); each corpus recorded one miss, one store, and 30 hits.
  PNG bytes, plan token, rejection/verifier result, clip, scale, new rect, and
  prepared-plan identity matched the legacy control. The final gate rerun's
  dense-unrotated Stage-A capture share was 0.503762 (GO threshold 0.20);
  retained Python memory stayed
  within the structural bounds. Live commit behavior and rollout defaults are
  unchanged. Record: `plans/archive/task13-p3d-interpretation-reuse.md`.
  **Registered follow-ups — not implemented in P3-D:** (a) prove whether
  `_span_origins` can derive its tuple from the already materialized rawdict;
  (b) prove node rect/quad coverage before replacing full-page interpretation
  with a halo scissor; (c) investigate reuse around `get_drawings()` tracing;
  (d) reduce rawdict extraction-shape/Python-dict construction cost; (e)
  investigate once-per-accept interpretation reuse in the live engine; (f)
  define complete snapshot/reset governance for the process-global
  `fitz.TOOLS` small-glyph, quad-correction, and anti-alias settings.
- 2026-08-29 (Task 13 — **P3-D manual smoke FAIL → rotated-page text-edit
  geometry fix**, same branch): the rotated GUI smoke
  (`docs/history/reports/2026-08-29-p3d-manual-smoke-attempt.md`) exposed
  three pre-existing defects, none introduced by P3-D: the model's public
  text-geometry surface was unrotated dict space while the View is displayed
  space (outlines/hover/click/editor all landed at the unrotated location on
  every `/Rotate 90/270` page — GUI text editing there had never worked);
  an untouched session reported a font override (`"Helvetica"` vs the UI alias
  `"helv"`) and lost the Tier 0 plan; and the plan-preview hook refused rotated
  editors. Fixed at the model boundary (`model/geometry.py` chokepoints,
  `PDFModel` displayed-space wrappers, `edit_text`/`derive_tier0_preview_target`
  entry derotation, legacy insert bounds = `unrotated_page_rect`) plus view
  changes (style-override comparison through `_font_alias`, rotated
  plan-raster + frozen-first-frame counter-rotation through one shared
  `PROXY_COUNTER_ROTATION` table incl. 180°). An adversarial review round
  found and fixed three more red-first (180° frozen frame, font
  pick-and-revert override, legacy clamps vs displayed `page.rect`). Record:
  `plans/archive/task13-rotated-page-text-edit-geometry.md`. **Manual retest
  still owed** (interactive only): the smoke procedure in the report.
  **Registered follow-ups (pre-existing, rotated-*text* proxies too):** (a)
  drag-end rect derivation (`pdf_view.py` mouseRelease ~4979-4991) uses the
  proxy's top-left for 90/180/270 proxies whose anchor is
  `(x1,y0)`/`(x1,y1)`/`(x0,y1)`, so a dragged rotated editor reports an offset
  `new_rect` (derive it from `proxy.sceneBoundingRect()` instead; plain
  click-then-Apply is unaffected, `new_rect` stays None); (b)
  `_clamp_editor_pos_to_page` clamps with unrotated widget dims for rotated
  proxies (fixed round 7: (a) and (b) are done, see the "Rotated-page box
  move" item above); (c) the add-text editor on a `/Rotate` page is drawn at
  `page_rotation` while `add_textbox` inserts with `rotate=page.rotation` in
  unrotated space, so the committed glyphs' on-screen orientation differs from
  the editor's — determine the real orientation with the pixmap-ink oracle and
  pass that rotation from `_create_add_text_editor_at_scene`; (d) the plan
  preview coordinator rasterises `clip | effective_verify_bbox` but the view
  paints the decoded PNG at local (0, 0) and discards `result.clip_rect`, so
  baseline-direction growth shifts the preview (rotation-independent; crop /
  offset by `result.clip_rect` in the controller); (e) the three older
  rotation helpers (`_dict_space_to_visual`, annotation derotate/rotate,
  `add_textbox`) should route through `model/geometry` thin wrappers; (f) the
  model geometry surface now round-trips through MuPDF float32 rects/points at
  `/Rotate 0` too (no exact-equality test exists; short-circuit at rotation 0
  if one ever needs byte identity); (g) `PDFModel._normalize_text_for_compare`
  is still missing (below).

### Task 14 P4 — Type0 hit-rate (census-gated)

- 2026-08-31 (**P4-B Fix A complete, stacked implementation**): V0c no longer
  treats a source substring anywhere in the spatial halo as proof that the
  target survived. It retains replacement extraction, then replays the patched
  stream and proves exactly one target `Tj`/single-string `TJ` at the declared
  splice with byte-identical decoded operand. Neighbor bytes and origins remain
  independently pinned; malformed/refused replay fails closed. Fix B and
  positive-hscale admission landed on subsequent stacked branches.

- [x] **Close duplicate-painter twin admission for V0c (2026-09-01, hardened
  the same day after a second Pro review).** Planning rejects identical
  painters whose mapped core quads overlap on both axes, while abutting shows
  and a genuinely disjoint 1 pt gap remain admissible. The former +1.0 pt
  fixture was itself an ~11 pt-overlap twin, not a legitimate neighbor. The
  first cut of the gate was still defeatable and was corrected: candidacy now
  compares FONT OBJECTS resolved through the registry (a second resource name
  aliasing one font dictionary was admitted before — resource names are not
  identity), extended to cloned dictionaries that differ only by subset tag
  and to capabilities the registry could not finish building, and every proven
  candidate's core is measured from its own text state (its capability's width
  at its own size, its own Tc/Tw through the same codec branch the target
  uses, its own Tz) instead of the target's advance scaled by a font-size
  ratio. The candidate core now envelopes both the baseline and its `Ts` shift:
  the earlier baseline-only correction still admitted a line offset cancelled
  by rise, while translating only the candidate opened a false-admit band at
  `rise >= 0.6*Tfs`. The envelope closes both holes for either sign. Font
  identity also excludes layout metrics: differing `/Widths`, `/W`, `/DW`, or
  `first_char` never proves different outlines, and `_same_font_object` no
  longer returns `False`. Identity-unproven single-string `Tj` candidates get
  exact extents only from raw-byte CID measurement or a widths-backed simple
  round trip; encoding-name equality and face-guessed widths stay bounded.
  Unprovable candidates (unresolvable font, unproven width, any `TJ` — replay
  drops the array's numeric items, so a leading kern moves the ink off the
  recorded origin) are BOUNDED by `_painter_reach` rather than refused
  outright, so a twin on another baseline stays editable. Under shear, the
  reach quad pads both x ends by the rise-envelope y extent times `|v|/|u|`;
  omitting that cross-term under-bounds large-rise candidates. Cost: ~15 ms for a
  275-way same-string bucket, with one registry resolve per distinct candidate
  resource. XObject-hosted twins remain the documented replay blind spot
  bounded by V0d.

- [x] **Remove the large-stream preview cost of V0c target-operator replay (2026-09-01).**
  A synthetic direct stream with repeated `Tj` operators measured 3.20 s cold
  and 5.95 s median across repeated in-process passes at ~2.5 MiB, versus
  4.1 ms median for a 4,070-byte stream. V0c now lexes the isolated Tier 0
  token or guarded-replays the isolated Tier 1 operator only; V0a retains the
  correctness-unbounded full-stream byte/hash proof.

- 2026-08-31 (**P4-B Fix B complete, stacked implementation**): Tier 1 now
  samples target background from a planner-derived, flag-immune font-metric
  quad while leaving the caller bbox untouched for origins, halo, growth edge,
  occupancy, and raster probes. Dense-CJK positive growth now agrees with
  `set_small_glyph_heights` on/off across `/Rotate 0/90/180/270`; vector,
  image, shading, boundary ink, and invisible white-on-white targets remain
  fail-closed. The production admission gap recorded at lines 927-938 is
  closed; process-global `fitz.TOOLS` test hygiene was closed by GATE16-1
  (2026-10-12, `conftest.py` pins the production flags).

- 2026-08-31 (**P4-B1 complete, stacked implementation**): positive finite
  horizontal scale is admitted with one raw/effective displacement contract.
  Raw advances remain token/kern inputs; fallback, Tier 1 growth, and metric
  background extents use `raw × Th`; TJ kern compensation is hscale-free
  because the common Th cancels. Zero/negative/non-finite values fail at the
  planner. The sealed-corpus rerun reattributed all 877 former hscale-only
  doc_0 shows to source-bindable (5,934 → 6,811), moved 88 TJ+hscale shows to
  TJ-only (42 → 130), and left unrelated/page-eligibility counters unchanged.
  **Reconciled 2026-09-01 after the duplicate-source-painter gate landed**
  (same sealed corpus, `--json --no-e2e`): `source_bindable` is unchanged at
  6,811, so the 877-show hscale figure stands. What changed is downstream —
  the new `duplicate_painter_only` bucket takes 187 doc_0 shows, so
  `all_gates_pass` is **6,624**, not 6,811, and `tj_array_only` drops 130 →
  112 (18 TJ shows now lose on duplicate as well and fall to `other`).
  `hscale_only` remains 0. The census output was privacy-scanned: no document
  text, basefonts, resource names, file basenames, or non-ASCII values.
  Augmentation Safety remains NO-GO; no font mutation or `store_shrink(100)`
  path was added.

- [x] **P4-B2 exact-painter-geometry read-only spike (2026-09-02,
  `task15/p4-b2-exact-painter-geometry-spike`, no merge).** The P4-B1
  duplicate-painter gate stays frozen at `49c98ee` (heuristic ceiling, verdict
  doc `plans/archive/2026-09-01-p4b1-final-review-verdict.md`, no interim hardening
  by user ruling). The spike (`scripts/painter_geometry.py`,
  `scripts/painter_evidence.py`, `scripts/measure_p4b2_shadow_census.py`,
  `scripts/benchmark_p4b2_painter_evidence.py`, five `test_p4b2_*` suites)
  bounds ink per glyph from MuPDF's own `fz_bound_glyph` inside a device hook,
  cross-checked by fontTools and the bboxlog, joined to shows by a
  `(gid, origin)` window search. Sealed corpus: 2,140 of the 2,146
  exact-quad-dependent admissions re-proven per glyph, 0 overlaps in the
  reach-safe set, 28 real overlaps among the 187 refused rows,
  `composed_all_gates_pass = 6,618` (GO thresholds 4,478 / 5,962 met,
  decidability 0.997). Matrix: 62 shapes, 0 exact false-safes; the
  adversarial review's stroke-ladder counterexample (degenerate control box
  + `Tr 1/2` pen bar) was reproduced and fixed fail-closed. Full numbers and
  the GO/NO-GO in `plans/archive/task15-p4b2-exact-painter-geometry-spike.md`.
- [x] **P4-B2 production slice (`task15/p4-b2-exact-painter-geometry-admission`),
  gated on the spike's GO.** **Closed 2026-09-04, all four §3.6 gates PASS:**
  Safety 0 production false-safes against the exact-arm oracle (sealed run,
  `glyf_box_violation`/`production_mirror_disagrees` both 0); Value
  `composed_all_gates_pass_production = 6,616 ≥ 5,962` GO threshold (spike's
  own 6,618, the 2-row gap fully explained by `glyf_degenerate` fallbacks);
  Perf same-session dense-bucket warm p95 ratio ≈ 1.34× ≤ 2× ceiling. The
  slice is complete on its branch; per user decision, **no merge, PR, or
  push** — see `plans/archive/task15-p4b2-exact-painter-geometry-admission.md`
  §6 for the full gate table and evidence. _Design, gates and original
  commit sequence in
  `plans/archive/task15-p4b2-exact-painter-geometry-admission.md`
  (slice 3). Slices 1 and 2 are committed, and the Codex "sol" adversarial
  review of them is closed (four findings, 2026-09-04: the on-disk restore
  claim narrowed to "identical to a never-edited document"; a fail-closed
  `PAGE_GEOMETRY_UNSUPPORTED` admission gate on the page frame — which also
  caught MuPDF rendering a non-quarter-turn `/Rotate` while every rotation
  accessor reports 0; `visual_baseline_direction` routed onto the frame;
  and a `BaseException`-safe stream restore). Premise correction from the 2026-09-04 probes: MuPDF ignores the
  glyf header (a zeroed header still renders the outline), and the 1-unit
  deltas are FreeType's `lsb − xMin` shift, so boxes are point-verified with
  a header cross-check, not header-trusted. **Slice 3 commit 3 landed
  2026-09-04:** `model/text_commit/glyph_boxes.py` (point-verified
  `glyph_unit_box` + `GlyphBoxCache` owned by `DocumentFontRegistry` + the
  re-homed geometry, TJ re-lex and Identity-H cursor replay), the extended
  `parse_truetype_glyph_program` sfnt pass, `read_embedded_font_program`,
  and the `model/ ↛ scripts//fontTools` AST guard —
  `test_scripts/test_glyph_boxes.py`, 29 tests, boxes bracket
  `fz_bound_glyph` with 0.0000-unit deviation on 300 simple + 30 composite
  gids. Two measured plan/instruction corrections are in the plan's §5
  logbook: the `hmtx` bearing of a gid past `numberOfHMetrics` comes from
  the trailing `leftSideBearing[]` array (the last-long-metric rule missed
  ink by 27 units), and a composite whose `lsb` disagrees with its header by
  more than a unit is refused rather than shifted (unmeasured on any face).
  A second commit closed a false-safe the advisor pass found in the re-homed cursor replay (a non-finite `/W` advance produced a SUCCESSFUL prediction at `(inf, nan)`, and NaN edges read as "no overlap") and added the five `tj_items`/`predict_glyphs` cells that commit 4 would otherwise have covered only indirectly.
  **Slice 3 commit 4 landed 2026-09-04:** the exact-first arm in
  `plan.duplicate_source_painter_detail` (keyword-only `streams`,
  `replacement_cids`, `glyph_boxes`; both painters bounded from their own
  outlines; `TJ` kerns re-lexed; aggregate AABB prefilter then per-glyph
  pairs; the new
  `identical source painter's glyph ink overlaps the target ink by …`
  refusal) plus `GlyphBoxCache.units_per_em`. The 16 `/W` rows and both R5
  core-band rows now REJECT (`test_p4b2_production_pins.py`'s strict-xfail
  twins are plain passing tests; its two characterizations are deleted), the
  falsification matrix gained a fourth `production` arm with **0 false
  safes** over its 62 shapes (recovering all 22 rows the `glyph_boxes=None`
  baseline arm still admits), and `test_p4b2_admission_gate.py` (32 cells)
  carries the raster-anchored composition. Three behaviour changes are
  recorded in the plan's §5 logbook and in PITFALLS: a twin raised clear of
  the target's real ink is now admitted (raster-proven; a rise inside the
  glyph height still refuses), a provably-different-glyph twin is refused on
  its measured overlap rather than on unprovable identity, and
  `_painter_reach` now requires an invertible text-space map — closing a
  pre-existing false safe (a rank-1 `Tm` with `1 Tr 8 w` painted a pen bar
  across the target and every pre-slice arm admitted it). **Slice 3 commits
  5+6 landed 2026-09-04:** `scripts/measure_p4b2_shadow_census.py` gained a
  fourth `production` arm — the REAL `plan.duplicate_source_painter_detail`
  called with the real kwargs `prepare_plan` passes (streams,
  `capability.cid.encode_strict(target_text)` as `replacement_cids`,
  mirroring the funnel's own self-check, so the "after" ink never widens
  past "before" — a stated value-measurement limitation, not a safety one),
  cross-validated glyph-by-glyph against the spike evidence bundle's O1
  device boxes via a same-preconditions derotated-space mirror that is
  NEVER itself the source of a row's verdict (an AABB is not
  rotation-invariant, so a box built in the mirror's space cannot stand in
  for the frame-space one in the overlap test -- see PITFALLS). On the
  synthetic two-document corpus: `production_rows_decided == twin_rows ==
  4` (0 fell to reach), `production_exact_safe == 2`,
  `production_overlap == 2`, `glyf_box_contains_o1 == 16`,
  `glyf_box_violation == 0`, `production_mirror_disagrees == 0`,
  `composed_all_gates_pass_production == 2`; a third, corrupted-glyf-header
  document (red-first) produces `production_ambiguous.glyf_header_disagrees
  > 0` and still `glyf_box_violation == 0`. The sealed-corpus run is NOT
  part of this commit -- pending, run by the orchestrator:
  `python scripts/measure_p4b2_shadow_census.py <sealed corpus paths> --json`.
  `scripts/benchmark_p4b2_admission.py` (new) timed `prepare_plan` cold/warm
  on the two-painter fixture (cold p50 50.4 / p95 53.9 ms; warm p50 20.0 /
  p95 21.2 ms, n=30) and a 275-twin dense same-bytes bucket (cold p50 83.8 /
  p95 102.7 ms; warm p50 62.0 / p95 114.5 ms, n=10 -- first recording, no
  prior P4-B2-admission baseline to compare against), glyph-box parse cost
  (25.8 ms / 1,000 gids on the fixture program), and the preview keystroke
  path against the P3-C benchmark's own recorded baseline (warm p50 267 /
  p95 316 ms): current warm p50 98.5 / p95 113.3 ms -- well inside "no
  regression beyond noise" (machine variance, not attributed to this
  slice). **Review round 2 (Codex "sol") on slice 3 is closed 2026-09-04**
  (two findings, one commit, red-first): (A, high) the exact arm carried
  the advance/reach path's 0.05 pt epsilon into an EXACT ink test, so a
  real overlap up to 0.05 pt read as safe — the padded boxes are already
  the conservative bound (one font unit = 0.047 pt at upem 256 / 12 pt, so
  the epsilon was subtracting back the whole pad), and
  `plan._glyph_ink_overlap` now refuses any STRICTLY POSITIVE depth on
  both axes (prefilter admits only at depth ≤ 0), with the reach and
  simple-font advance paths deliberately left at 0.05 (different bounds,
  different residuals) and the refusal string moved to `.4g` so a
  hundredth-of-a-point refusal no longer prints `0.000pt`; measured, the
  abutting-twin row is NOT lost on the builder face (padded boxes still
  clear by 0.9375 pt = 20 units). (B, medium) the census counted an O1
  containment violation (or a mirror disagreement) and then still
  classified the row `production_exact_safe` under `status: "ok"` — such a
  row is now `production_ambiguous.oracle_violation` (an `overlap` verdict
  is left alone on purpose: downgrading it would inflate
  `composed_all_gates_pass_production`), `report()` emits the closed
  `status: "oracle_violation"` while still printing every counter, and
  `main()` exits 4. **Sealed-corpus re-run: done (commit 7, 2026-09-04).**
  Two sealed runs, `f7e859c` (pre-finding-A-fix, 0.05 pt epsilon) and
  `ee530a8` (post-fix, strict-positive overlap): every counter identical
  except the new `production_ambiguous.oracle_violation = 0` key,
  `status: "ok"` both times. `composed_all_gates_pass_production = 6,616`
  — unchanged by finding A's fix on this corpus (no row's padded overlap
  fell in the 0-0.05 pt band) — clears the 5,962 GO threshold with 654
  rows of headroom; against the spike's own 6,618 the 2-row gap is the
  105 `glyf_degenerate` glyphs falling to reach (2 of them inside
  `production_delta_exact_safe`). Same-session PERF re-run (worktree of
  the pre-slice-3 tip `6b32184` vs. this tip, alternating, same
  interpreter): dense-bucket warm p95 ratio ≈ 1.34× ≤ the 2× ceiling —
  PASS. **All four §3.6 gates pass; slice CLOSED, no merge/PR/push (user
  decision).** Full gate table and evidence: `plans/archive/
  task15-p4b2-exact-painter-geometry-admission.md` §6._
  Requirements bound by the spike: per-glyph
  control boxes from the embedded program (glyf header bbox = FreeType control
  box on 2,998/3,001 probed glyphs, ±1 unit on the rest — carry a 1-unit
  tolerance or parse the points) placed by the cursor replay, with the O1
  device only for `trace_load_bearing` rows (4.2 %); the TARGET's old ink and
  the replacement ink both bounded from outlines (declared advance never an
  ink bound on either side); any unattributed painted glyph over the target
  ⇒ ambiguous (7 rows on the corpus); stroke modes conservative from the
  bboxlog rect and fail-closed on any empty glyph box in the *spike*; in
  production, which runs no bbox device, every non-fill render mode is
  ambiguous by rule (MuPDF's stroke expansion uses max|ctm element|, which
  undershoots a rotated pen by √2 and a sheared one by up to 2 — PITFALLS "MuPDF's stroke-text bbox
  expansion"); ambiguous/unavailable fall to reach; document-level
  `(font_xref, gid)` bound cache; evidence built before `page_fingerprint` so a
  later mutation invalidates it; `model/` may not import fontTools. The slice
  is a different gate from the measured one (glyf boxes, no O1 device): the
  re-run census puts the rows it cannot reproduce at
  `trace_or_device_load_bearing 947 / 22,708` (4.17 %; 2 device-only rows,
  0 rows carrying `oracle_disagreement`), so re-validate box ⊇ rendered bound
  on the rows it decides. Reach's own core-band false admit
  (`second_dy=±7.3`) stays a known residual until the exact arm covers it.
- [x] **Audit `Page.transformation_matrix` on rotated pages** (filed from the
  P4-B2 spike; **closed 2026-09-04 as slice 2** of
  `plans/archive/task15-p4b2-exact-painter-geometry-admission.md`). PyMuPDF drops the
  CropBox origin and `/UserUnit` when `/Rotate ≠ 0` (`(2,0,0,-2,-100,1484)` at
  rotation 0 vs `(1,0,0,-1,0,H)` at 90) — and the audit found the sibling half
  wrong too: `page.rotation_matrix`/`derotation_matrix` always drop
  `/UserUnit` and size themselves from the UNCLIPPED CropBox. **Design revised
  from the filed plan**: capturing the base inside a `set_rotation(0)` window
  was rejected, because that window permanently flips `doc.is_dirty` on a
  clean document; the frame is reconstructed arithmetically instead.
  `model/text_commit/transforms.py` gained `read_user_unit`, `PageVisualFrame`
  (`base`, `rotation`, `width0`, `height0`, `user_unit`; `quarter_turn`,
  `visual`, `inverse`) and `page_visual_frame(page)`, and five sites moved to
  it in one commit: `map_text_quad_to_visual` (new keyword-only `frame=`),
  `plan._page_visual_matrix` + `_grown_verify_bbox`,
  `inspect._origin_in_page_space`, and the dict↔visual pair
  `pdf_text_edit._dict_space_to_visual` / `verify._visual_bbox_to_dict_space`
  (which take `quarter_turn` alone — measured, `get_text('dict')` geometry IS
  base space; the two sides' defects cancelled in the round trip, so they had
  to move together). `plan._classify_common` derives the frame once per
  prepare and threads it through the gate calls. 130 new ink-anchored tests in
  `test_scripts/test_text_commit_visual_frame.py`: 8 page shapes × 4 rotations
  (32/32 cells; `E@180` is the discriminator no wrong formula passes), 13
  `/UserUnit` semantics cells, 4 edge page shapes, plus premise pins. Not
  touched, deliberately: `inspect._update_page_geometry`'s raw-matrix fold (a
  staleness signal, not geometry). `transforms.visual_baseline_direction` was
  left on the page matrices as "immune" (linear part only) and moved onto the
  frame anyway in the review round — immune is not the same as correct, and
  the page matrices must not be readable from that module at all. See
  PITFALLS (six entries).
- [x] **`model/geometry.py` shared the rotated-page defect** (filed 2026-09-04; fixed in round 16 as F15-G1-UU-ROT).
  The point/rect converters (`visual_to_unrotated_*`, `unrotated_to_visual_*`, `unrotated_page_rect`) now take the
  quarter turn from `transforms.page_visual_frame(page).quarter_turn` on a rotated page (page matrices only for an
  unprovable frame): the `/UserUnit 2` and unclipped-CropBox offsets measured here are gone, and the strict xfail in
  `test_watermark_rotated_pages.py` was removed. Still open: `model/tools/annotation_tool.py` helpers use the page
  matrices directly (see F15-G1-UU).
- [ ] **`interpret_page` dirties the document on every rotated-page verify or
  preview** (filed 2026-09-04 from slice 2; pre-existing, not introduced
  there). `model/text_commit/interpretation.py:105-112` opens a
  `set_rotation(0)` … `set_rotation(old)` window to build a derotated display
  list; measured, `Page.set_rotation` flips `doc.is_dirty` False→True and
  restoring the original rotation does NOT restore the flag. So a read-only
  verification or preview on a rotated page leaves the document looking
  modified. No known user-visible impact today (nothing in the app reads
  `is_dirty`), but it is a landmine for any future unsaved-changes prompt, and
  it is the reason slice 2's page frame is computed rather than captured.
- [ ] **Simple-font glyph route for the exact painter geometry arm** (filed
  2026-09-04, P4-B2 production slice, closing docs). The exact arm
  (`plan.duplicate_source_painter_detail`'s exact-first composition,
  `model/text_commit/plan.py`) addresses only the CID population: a
  simple-font target or twin still falls back to the pre-slice advance-quad
  path unchanged, a stated residual (removing it would refuse every Latin
  document whose target word appears twice in the same font, unmeasured
  regression). Follow-up: a simple-font glyph route, TrueType
  `cmap`/`Encoding` → gid, feeding the same `glyph_unit_box` bound
  `glyph_boxes.py` already has for CID fonts.
- [ ] **The 105 sealed-corpus `glyf_degenerate` glyphs are unmeasured beyond
  their count** (filed 2026-09-04, P4-B2 production slice, closing docs).
  The sealed run's `production_ambiguous.glyf_degenerate = 105` (of
  `twin_rows = 22,708`) falls to the reach path — fail-closed, so it costs
  Value not Safety — but what these glyphs actually are is unconfirmed on
  the sealed corpus; the working hypothesis (from `glyph_boxes.py`'s
  `glyf_degenerate` slug, `GLYPH_BOX_REASONS`) is a zero-area point box on
  a glyph whose `glyf` entry has data. Needs its own probe against the
  sealed corpus's fonts to confirm or correct that hypothesis before
  deciding whether it is worth recovering.
- [ ] **P4-B2 benchmark comparisons are machine-state sensitive** (filed
  2026-09-04, closing docs; not a defect, a standing caveat for whoever
  reads a P4-B2 benchmark number next). `scripts/benchmark_p4b2_admission.py`
  (commits 5+6) and this closing commit's own same-session PERF re-run both
  show absolute millisecond figures — and even one non-gate cold p95 —
  swinging by roughly 2-3× across separately-run sessions on the same
  machine (plan's §5 "Commit 7" logbook). Only same-session, same-machine
  ratios (like the §3.6 PERF gate) are load-bearing; a cross-session
  absolute number in any P4-B2 doc is context, not a commitment. No fix is
  proposed — this is a note to whoever next compares a P4-B2 benchmark run
  against an old one, not an action item with a design.

- [x] **Exact transactional rollback for `AppliedPatch.revert` (Codex
  adversarial review, 2026-09-02; pre-existing since P3-C `4adc34f`/`97993c4`,
  not P4-B2). Closed 2026-09-04 as slice 1 of
  `plans/archive/task15-p4b2-exact-painter-geometry-admission.md`.** `AppliedPatch.
  prior_streams` held decoded bytes only and `revert` rewrote with
  `compress=True` (`model/text_commit/patch.py:78-99`), so a FAILED live
  verification (`model/text_commit/engine.py:274`) left an
  originally-uncompressed or multi-filter content stream as a single
  `/FlateDecode` object with different raw bytes; `/DecodeParms` survival is
  size-dependent (MuPDF skips Flate on tiny streams and drops the key).
  Measured (PyMuPDF 1.27.1): single-Flate streams round-trip byte-identically;
  `doc.is_dirty` flips on ANY `update_stream` (even a byte-perfect no-op) and
  nothing in the app reads it; the same rewrite already happened on successful
  tier-0 commits and on undo/redo (`model/edit_commands.py:394,460`). Severity
  low. **Design revised during implementation** from the per-key
  `xref_set_key`/`/Length`+`/Filter`+`/DecodeParms` plan above to a
  whole-object restore, after measuring that (a) `xref_get_key` cannot
  distinguish an absent key from `null` (`xref_set_key(x, 'DecodeParms',
  'null')` leaves a literal entry) and (b) a wrong `/Filter` is silent
  content loss that saves cleanly (new PITFALLS entry) — a per-key design
  cannot fail closed against that. Fix: `model/text_commit/inspect.py`
  gained `StreamStorage` (`xref`, `raw`, `obj`, `decoded`),
  `capture_stream_storage`, and `restore_stream_storage` (raw bytes via
  `update_stream(compress=False)`, then the FULL object dict via
  `update_object`, then a three-way self-check with a non-raising fallback
  to the pre-slice `update_stream(decoded, compress=True)` behaviour);
  `AppliedPatch` gained `prior_storage`, captured in `apply_patchset`'s
  existing per-stream loop before the first mutation; `EditTextCommand`
  captures pre-/post-commit storage and restores it after the undo/redo
  patch replay. `new=` on `update_stream` confirmed inert (1.27.1), so
  dropped from the design. Failure-injection tests over uncompressed /
  FlateDecode / Flate+DecodeParms(PNG-Up) / `[/ASCIIHexDecode
  /FlateDecode]` / tiny / indirect-Length-and-Filter / two-stream-array
  streams, plus real `TieredCommitEngine.commit` FAILED + raising-verifier
  legs, undo/redo, a corruption-fallback negative, and a save+reopen leg —
  all assert raw bytes, the `xref_object` dict, and decoded bytes are
  unchanged after a rejected commit or replay. Related: WS-B/F4 live-commit
  revert atomicity; PITFALLS "AppliedPatch.revert used to lose the original
  stream storage encoding (fixed, Task 15 P4-B2 slice 1)".
- [ ] **Re-encode a successful commit's new bytes under the original filter
  chain (deferred, filed 2026-09-04 alongside the exact-rollback close
  above).** A SUCCESSFUL Tier 0/1 commit's `apply_patchset` still writes the
  patched stream via a fresh `update_stream(new_bytes, compress=True)` —
  the NEW bytes land as MuPDF's own chosen encoding, never re-encoded under
  whatever filter chain (Flate+Predictor, ASCIIHex+Flate, indirect
  Length/Filter, …) the stream originally used. `restore_stream_storage`
  only ever restores a stream to bytes it has ALREADY seen (a captured
  pre-/post-commit snapshot) — it has no way to re-express brand-new
  spliced content under an arbitrary original filter chain. Out of scope
  for P4-B2; no known correctness impact (decoded content, fingerprints,
  and every reader here are storage-encoding-agnostic), just a fidelity
  gap for a document whose producer or a byte-level diff tool cares about
  the exact filter chain of freshly-edited content.

- [x] **Close P4-B Pro-review round 4 direct-path findings (2026-09-01).**
  Candidate rise uses a baseline/rise envelope plus the sheared reach y-cross
  term; glyph identity is separated from width/layout metrics; caller and
  derived bboxes share one arity/conversion/renderability predicate; and the
  Type0 census mirrors the effective source-advance product without stealing
  `hscale_only` attribution. Red tests cover all four findings and the
  adversarial design holes. The sealed-corpus `--json --no-e2e` rerun was
  unchanged: `source_bindable` 6,811, `all_gates_pass` 6,624,
  `duplicate_painter_only` 187, `tj_array_only` 112, `hscale_only` 0; doc_1
  remains zero past eligibility. The corrected edge shapes are absent from
  this corpus, so the safety fixes caused no ordinary-corpus reattribution.
  The aggregate JSON contained no document text, filenames, basefonts,
  resource names, or non-ASCII values.

- 2026-08-30 (Task 14 P4 candidate census, review-corrected): the
  replacement-encodable funnel's 100% value is only a self-proxy. Among
  already-bindable `doc_0` shows, just **15.5%** of the document's
  corpus-union characters are encodable in that show's font today (CAD seed
  10.3%; fullwidth digits/punctuation 4.1%), so a character copied from
  elsewhere in the drawing fails the encoding gate about 85% of the time.
  Commit 3b's all-face proof found 48 strict exact and 95 shared-program
  `doc_0` fonts. The shared-program rule admits byte-identical TTC
  `glyf`/`loca`/`hmtx` programs only when every face agrees on the requested
  character's GID. Those 143 eligible fonts contain 4,292 bindable shows.
  The Commit 3c Codex finding is closed: shared-program admission now also
  pins `head`/`hhea` interpretation fields, fails closed over every unexcluded
  table's presence and bytes, and requires per-GID glyph/metric agreement;
  the 2026-08-31 census numbers were unchanged.
  Unit B is 3,326.47 augmentation vs 127.00 hscale vs 12.29 whole-`TJ`
  show-equivalents, so augmentation leads hscale by 26× on value.
  The strict unique-face row remains 0 and the unrestricted upper bound
  remains 5,006.08. The mutation-premise matrix passed serializer, descendant
  rewrite, KEEP reopen, raster identity, multi-object revert, cross-page
  staleness, and AES-256 gates. Cache visibility is the blocker: in-place and
  descriptor-repoint/new-xref rewrites stay invisible; reopen works; only the
  process-global `fitz.TOOLS.store_shrink(100)` refreshes the same handle, and
  the single-threaded probe cannot prove worker exclusion during that flush.
  **Safety is NO-GO, so Priority GO is hscale.** If coordinator-level
  exclusion or a non-global same-handle refresh later flips Safety, the same
  corpus numbers make augmentation the pick. The 1,642 bindable shows on
  unproven fonts remain a candidate-list item for P4-B.
  Separately, hscale leads Unit A at 877 newly bindable shows versus whole-`TJ`
  42. (2026-09-01 note: "bindable" is the binding funnel, which the
  duplicate-source-painter gate sits downstream of. It is unchanged at 6,811;
  end-to-end admission on the same corpus is 6,624 — see the reconciliation
  in the duplicate-painter entry above. The 877/42 comparison between the two
  candidate units is unaffected, since both are measured at the same stage.) Relaxing the unchanged 4 MiB replay budget exposes a **16,549**-show
  stage-loss upper bound, but those shows can still fail downstream gates, so
  the bound belongs to neither Unit A nor Unit B. Budget relaxation stays the
  §9 item (`TODOS.md:473`): its latency half remains open. Record:
  `plans/archive/task14-type0-augmentation-census.md` §7.
  Fresh artifacts persist zero malformed-replay pages/shows, zero shared-
  content-stream pages/shows, and zero unreadable-content pages in both corpus
  documents. The census rejects all three conditions structurally, uses a
  one-pass fail-closed stream-owner index, and closes ToUnicode reject details
  over the 15 code-authored literals plus `missing_detail`.
  P2 confirms `xref_set_key(..., "DescendantFonts/0/DW", ...)` destroys the
  array, so descendant mutation must use parse → modify → serialize. P9
  confirms an earlier Tier 0 command's undo refuses stale after font mutation
  and leaves the document unchanged.

#### Pre-existing defects discovered incidentally during P0-C (register only; not in P0-C's scope)

- `PDFModel` has no `_normalize_text_for_compare` method. Referenced by
  `controller/pdf_controller.py`'s `_resolve_cross_page_move_source_span_id`
  (its ambiguous-multi-candidate ranking path, reached when
  `find_overlapping_runs` returns more than one span for a cross-page
  move's source rect) and by `test_scripts/test_track_ab_model_regressions.py:28`.
  Found 2026-08-12 while writing P0-C phase 1's cross-page-move test;
  worked around there with a single-token target text (word-boundary
  tokenization guarantees exactly one candidate span, avoiding the buggy
  path) rather than fixed, per the standing scope-freeze discipline.
  **Controller side fixed (round 7, HIST-3):** the controller now ranks
  with its own `_normalize_run_text` (pinned by
  `test_cross_page_move_source_resolution_ranks_overlapping_candidates_by_text`).
  Still open: the script-style `test_track_ab_model_regressions.py:28` helper
  (not pytest-collected) calls the missing model method.

## Task 16 — Legacy-path fidelity, found by manual test (2026-09-04)

Queued **after** everything already scheduled above. Found while manually
testing `task15/p4-b2-exact-painter-geometry-admission` on
`test_files/[HVAC_DWG_PDF]` page 1 (unrotated). None of these
are regressions from that branch: the app ships `engine="legacy"`,
`max_tier=0` (`model/text_commit/dto.py:210-212`), populated only by
`TextCommitSettings.from_env` at `main.py:98,143`, with **no GUI toggle and no
QSettings override** in `view/` or `controller/` — so the tiered engine and the
P4-B2 admission gate never execute for a real user. Full evidence in the
session memory note `project-legacy-engine-is-the-shipping-default`.

Reproduction facts, all measured (not inferred):

- Synthetic bold in Office-exported CJK PDFs is a **duplicate painter pair** —
  `get_texttrace()` gives `type=0` (fill, seqno 10) plus `type=1` (stroke,
  lw 0.702, seqno 11) over the same glyphs, because 標楷體
  (`DFKaiShu-SB-Estd-BF`) has no bold face. Span `flags=8`: **the bold bit is
  not set**, so flag- or name-based bold detection misses it entirely.
- Legacy commits fill-only and drops the stroke twin → bold silently vanishes.
- Legacy paragraph mode treats a whole table row (cells sharing a baseline) as
  one paragraph → sibling cells `[SITE_SHORT]`/`[CLIENT_ACRONYM]` were swallowed outright.
- Tiered + **strict** refuses both with zero mutation (verified AFTER==BEFORE):
  title → `type0_tounicode_unparseable`, table row → `multi_span_target`.
  Non-strict tiered falls back to legacy and reproduces the identical damage,
  so any re-test **must** set `TEXT_COMMIT_STRICT=1` or refusal and damage are
  indistinguishable.

### T16-1 — Surface the degradation the model already reports (no dependency; gates T16-3's default flip)

**DONE 2026-09-05** (commit `bdea104`, plus cross-page follow-up in same commit).
`CommitOutcome` already carries
`status=DEGRADED_COMMITTED, tier=TIER2_LEGACY,
warnings=('legacy_engine_fidelity_untracked',),
degraded_reason='legacy_redact_reinsert'`. The View never shows it, so a user
only catches lost bold/structure by eye. Wire it to a non-blocking notice.
Smallest item here and it does not change any fidelity behaviour — do it first
so later items are observable. "Refuse loudly rather than degrade quietly."

Added `PDFController._is_legacy_baseline_degrade` (checks status and degraded_reason),
`_legacy_baseline_degrade_message` (non-blocking toast naming the engine + untracked bold/structure),
and `_notify_legacy_baseline_degrade` with shared dispatch logic. Two call sites:
`edit_text()` (after the `_is_notifiable_degrade` check — mutually exclusive by construction
per the legacy commit chain), and `move_text_across_pages()` (own gate with same helpers,
red-first pin: `test_cross_page_move_surfaces_source_degrade_under_legacy_engine`).
Acceptance: every legacy redact+reinsert commit surfaces exactly one notice per edit/move.
Pins: `test_scripts/test_text_commit_degrade_visibility.py` (22 passed); cross-page regression
sweep (11 passed).

### T16-2 — Paragraph mode must not span table cells (no dependency)

**DONE 2026-09-05** (commits `2ba237e` + `0f8658c` + `11f6ee2` + `40284c2` + `fcda7f6`;
`model/text_block_parsing.py::_build_paragraphs`, tests in
`test_scripts/test_paragraph_table_cells.py`). A block is now split into
sub-paragraphs by three geometric rules — an intra-PyMuPDF-line cell cut at
`_CELL_GAP_RATIO = 0.80` x font size, a same-baseline re-join at
`_SAME_BASELINE_GAP_RATIO = 3.0` x font size (MuPDF opens a new "line" at every
positioning jump), and transitive column grouping at
`_COLUMN_OVERLAP_RATIO = 0.50` x-overlap. HVAC page 1 block 6 now yields the four
real cells instead of one row-wide paragraph. Measured evidence and the rejected
alternatives are in `plans/archive/task16-legacy-path-fidelity.md` (Log, 2026-09-05).

Red-first baseline (7 tests): 4 failures on cell-split expectations, 3 guard pins
(ordinary word gap, vertical block, wrapped paragraph). Green: all 7 + paragraph
touching suite (269 total). Review round 1 (11f6ee2): one real defect — vertical
exemption was gated inside `_block_paragraph_units` only, so `_build_paragraphs`'s
rule (b) still split vertical blocks (measured 692 blocks shredded on HVAC; page 4
b167 wrapped title 1→2 paragraphs, page 17 greedy merge 12 orphans across 2 blocks).
Fixed by extracting `_block_splits_cells(block_runs)` and calling it at both sites;
control-flow bug not a tuning one. Review round 2 (40284c2/fcda7f6): two findings —
(1) predicate-consistency hardening: passed `split_cells` into `_block_paragraph_units`
rather than calling twice (agreement by construction); (2) widened `VERTICAL_PAGES`
pins from (4,17) to (3,4,5,17) to cover measured shredding on pages 3/5 (46→51,
48→54 blocks). Both reviews verified red-first before fix. Final suite: 219 passed /
1 skipped / 5 xfailed over paragraph+text_block+text_extraction+char_run+edit_text;
50 more on remaining paragraph-touching files (50 rounds, geometry stability, etc);
ruff+mypy clean.

**Known miss, deliberately shipped.** The two gap populations overlap: 1.pdf's
per-word prose gaps reach 2.42x while genuine same-baseline cell boundaries go
down to 1.40x, so no threshold separates them. `_SAME_BASELINE_GAP_RATIO = 3.0`
resolves it in the prose-preserving direction, which leaves tightly-set
label/value pairs in one paragraph — e.g. HVAC pages 2+ `Revision No.` | `Bb`
(2.10x) and `審查結果` | `□同意認可(Code1)…` (2.11x): editing the label in
paragraph mode still redacts the value. Separating those needs a signal beyond
gap-to-font-size (ruling lines from `page.get_drawings()`, or a per-page column
model). Not scheduled; revisit if a manual test hits it.

### T16-3 — `parse_tounicode_strict` v2: array-destination bfrange (no dependency)

**Status:** All criteria DONE 2026-09-05.

`model/text_commit/cid_fonts.py:412` used to refuse the
`<lo> <hi> [<d1> <d2> …]` form (legal per PDF 32000-1 §9.10.3) because an
earlier adversarial round caught the legacy parser fabricating mappings for it
(`wf_a084d864-566`). Corpus impact is small by count but dominant by reach:
HVAC 260/261 Type0 fonts parse OK and **the single failure is the 標楷體 body
face**; `01_報告書.pdf` has exactly one Type0 font and it fails. Until this
lands, tiered cannot touch the main CJK face of either corpus document, so this
outranks further admission-gate work — the gate is already better than what
real documents can reach.

**Acceptance criteria.** The default flip is part of this item, not a follow-on:
unblocking the parser is worthless while the engine that uses it stays off for
every real user.

1. **DONE 2026-09-05** (commit `58e21f5` + docs `209574f` + correction `b63fafc`).
   Array-destination bfrange (`<lo> <hi> [<d1> <d2> …]`) now parses well-formed arrays
   exactly and refuses malformed ones under 8 new code-only details. Red-first
   against the current `type0_tounicode_unparseable` refusal: 7 new tests, all
   failed before implementation (`7 failed, 7 passed`), all green after. Corpus
   impact measured: HVAC 261/261, `01_報告書.pdf` 1/1 Type0 fonts parse OK.
   Verification: `test_text_commit_cid_hex_tj.py` 70 passed; dependent suites
   150 + 339 passed (cid_fonts tests + 11 suites); ruff + mypy clean. Review round 1
   (209574f/b63fafc): two doc-only findings on ARCHITECTURE.md parenthetical
   (retired blanket refusal statement, corrected false claims) — no production code
   changed. Red-first guard tests: 2 new tests, both failed on HEAD, green after.
2. **DONE 2026-09-05** (included in `58e21f5`).
   The fail-closed property that motivated the v1 refusal is preserved. v2 validates
   destination array length against the `<lo>`–`<hi>` span and refuses on any mismatch,
   short array, or non-UTF-16BE destination. Deliberately malformed arrays still refuse
   (pinned: array-element-count mismatch, unterminated/nested/unopened bracket, non-hex,
   empty, non-strict UTF-16BE, source-code position; 8 new code-only details). Legacy
   parser striding-over behaviour is excluded by construction.
3. **DONE 2026-09-05** (measured by same scan).
   Corpus funnel moved to HVAC 261/261 and `01_報告書.pdf` 1/1 Type0 fonts
   parsing OK (from 260/261 and 0/1 respectively). Census assertion closed in
   `test_glyph_overlap_census.py` (now uses well-formed then length-mismatched array).
4. **DONE 2026-09-05** (flip at `ed55b35`; review round 1 at `1dd3bc1` and
   review round 2 the same day — see the sub-bullets below for what the two
   reviews changed). `TextCommitSettings.engine`
   default flips `"legacy"`
   → `"tiered"`, demoting
   `TEXT_COMMIT_ENGINE` to a kill switch — `TEXT_COMMIT_ENGINE=legacy` must
   still work, and a test must pin it. Rationale (agreed 2026-09-05): a user
   cannot judge which engine to pick, and fidelity-preserving commit is not
   something they should have to switch on. `max_tier` stays `0`; Tier 1 is a
   separate gate, not part of this flip.
   - **Gated on T16-1.** `strict` stays `False`, so a flipped default means
     tiered refuses and falls back to legacy *silently* unless the degradation
     notice exists. Today's behaviour is equally silent, so this is not a
     regression — but the flip is the moment the fallback becomes the common
     path, and shipping it unannounced would bury exactly the failure this
     whole task came from.
     **Review round 2026-09-05:** as shipped at `ed55b35` the fallback was
     *not* silent — the Task 12 P0-C pre-commit consent modal fired on
     essentially every ordinary edit (measured 12/12 across three real
     fixtures; 20/20 in the latency A/B), i.e. a blocking `QMessageBox`
     **plus** the T16-1 toast per edit. The Task 12 endorsement covered
     cross-page moves only. The gate is now an opt-in,
     `TextCommitSettings.confirm_degrade` / `TEXT_COMMIT_CONFIRM_DEGRADE=1`
     (default off), which restores the premise this criterion was accepted
     under. Stated at its real frequency so it is not rediscovered as a
     surprise: the T16-1 notice that replaces the modal fires at the *same*
     rate the modal did — the same Tier 0 reject rate drives both — so what
     ships is **one 5 s non-blocking warning toast per text edit**. That is
     this criterion's own T16-1 gating working as intended, and the rate
     falls on its own as Tier 0 starts accepting (T16-3 parser, then T16-4). Two more review fixes landed with it: `REJECTED_UNSUPPORTED`
     (the newly-live signed/widget-page reject) now has a user-facing
     message instead of vanishing silently, and
     `page_has_widgets_or_signatures` is fail-closed in both halves and
     catches `fitz.mupdf.FzErrorBase`. The GUI-integration pins the flip
     commit added (`test_no_jump_editor_geometry.py`,
     `test_multi_tab_plan.py`, `test_cross_page_text_move.py`) are reverted:
     the modal was the reason they hung, so the shipped default is again
     covered end to end.
     **Review round 2 (2026-09-05), two more newly-live surfaces:**
     (a) `page_has_widgets_or_signatures` read `/SigFlags > 0` as "signed",
     but that flag only *declares that signature fields exist* — PyMuPDF
     writes `3` for a never-signed placeholder — so any unsigned contract
     **template** became uneditable on every page, with a refusal message
     that was false on both of its clauses. It now requires a `/FT /Sig`
     field with a non-null `/V`, fail-closed at every unreadable step.
     Round 9 (PYMU-SIGFLAGS-1): the probe no longer short-circuits on
     `get_sigflags() <= 0` (`-1` = key absent, but the file may still be
     signed), so a signed file without `/SigFlags` keeps the append-only save.
     Round 10 (F10-SIG-1): an indirect `/Fields N 0 R` / `/Kids N 0 R` array
     is resolved instead of read as "unparseable" (which had made unsigned
     forms such as `test-large-file.pdf` uneditable on every page), and
     `/Fields` is read by key, not regex-matched out of an inline `/AcroForm`.
     (b) Tier 0 patch-replay undo became live and its `STALE_UNDO` refusal
     was mute: `PDFController.undo()/redo()` discarded `CommandManager`'s
     `False` and `_edit_result_to_message` had no branch for
     `STALE_UNDO`/`STALE_PLAN`, so an ordinary two-edit-then-undo sequence
     left the undo button lit on a stack that never moved again and said
     nothing.
   - **Follow-up, not done here:** there is no in-app kill switch. Both
     `TEXT_COMMIT_ENGINE=legacy` and `TEXT_COMMIT_CONFIRM_DEGRADE=1` require
     an env var and a restart. A Settings-UI surface for the text-commit
     flags is its own item (register under a future settings task).
   - **Follow-up, not done here (review round 2):** a `STALE_UNDO` refusal
     now speaks, but the undo stack is still *wedged* by it — the command is
     deliberately retained (pinned contract:
     `test_text_commit_boundaries.py::test_stale_undo_...`), so every command
     below it stays unreachable and the button stays enabled. Deciding what
     undo should do after a stale inverse patch (snapshot fallback? drop the
     tail? disable the button?) is its own design item.
   - Interactive edit latency measured before/after **in the same session on
     the same machine** (prior benchmark comparisons of identical code swung
     1.8×–3× across sessions and are not admissible evidence). Tiered adds a
     `prepare_plan` per edit; the keystroke/preview path must not regress
     visibly.

### T16-4 — Tandem commit for synthetic-bold painter pairs (depends on T16-3)

The real fix for the reported bold loss, and a **new capability, not a bug
fix**. `plan.py:1006` rejects any `render_mode != 0` as
`UNSUPPORTED_TEXT_STATE`, so the stroke twin can never be patched; editing the
fill run alone would leave a stale stroke ghost, which is exactly what the
duplicate-painter gate exists to refuse. Requires committing both painters of a
pair together. Largest item; do not start before T16-3.

**Premise corrected 2026-09-05 (design panel, three independent designs + two
judges):** the fixture has **no** fill/stroke painter pair — zero `1 Tr` in the
file. Each bold run is a single `2 Tr` show (`w = size/35`, `[<hex>] TJ`) that
`get_texttrace()` splits into two device spans. Retargeted scope: admit
`render_mode == 2` for single-string shows with a proven stroke ink bound
(pen is USER space: outset by half-pen under the CTM, not `Tm`; miter factor
`max(miterlimit, 0.5)` at the duplicate-painter reach branch), and admit
single-item `TJ` arrays, since `NOT_SINGLE_LITERAL_TJ` fires before the
render-mode gate for every one of the nine fixture shows. Two-item kerned
arrays stay Tier 1. Full plan with evidence, gates and red-first steps:
`plans/task16-4-tandem-bold-commit.md`.

**Expanded 2026-09-06 into T16-4X — glyph-coverage expansion**
(`plans/task16-4-glyph-coverage-expansion.md`; the tandem-bold plan is its
slices S1/S3). Census of the same day, measured not inferred: every one of
the 292 identity edits that reach the planner on four fixtures refuses
`not_single_literal_tj`; behind that gate **100 % of Office-exported shows**
are wrapped in `/P <</MCID>>` structure marked content that the Task 13
gate refuses as `mc_wrapper_not_pure_layer` (271/271 sampled shows, called
directly); 12 % of Office arrays are kerned, and the kerns are intra-word
pair kerns (288 boundaries inside words vs 20 word-gap kerns); Type3 is 65 %
of one fixture and 0 elsewhere; invisible text (`3 Tr`) is 334 shows on the
402-page fixture, where legacy re-inserted *visible* glyphs (the consented rebuild keeps `3 Tr` since round 17, F17-COL-2). Slices in order
(after the same-day adversarial review, wf_86b97cfb-496): S0 instruments
(both funnel scripts mirror pre-Task-13 gates and must call production gates;
`decode_literal_string` keeps a bare CR/CRLF raw where MuPDF reads one 0x0A),
S1 single-item `TJ` at **both** `NOT_SINGLE_LITERAL_TJ` sites (the CID leg's
hex-only check refuses every Type0 `[<hex>] TJ` too) + mode-2 pen proof, S2
render-inert marked content (struct/artifact/bare BMC), S7 invisible text,
S4/S5 (kerned `TJ` run binding with kern-sum collapse; fragment splice inside
one string — ordered by S0's measurements), S6 Type3 (MuPDF quantises the
advance to integer 1/1000 units — admit only integral `a·w·1000`), S3 stroke
bound at the duplicate gate last (smallest yield, riskiest, changes two named
p4b2 pins), docs. Zero-corpus
classes (mode 1, `'`/`"`, rise,
`/Differences`, Identity-V, CFF, non-Identity CMaps) stay refused by name
and are registered in the plan's §8. Ceilings registered there as T16-7
(Tier 1 default), T16-8 (`strict` default), T16-9 (Form XObject targets).

**S0 done 2026-09-06:** `pdf_lexer.py::decode_literal_string` bare EOL fix (CR/CRLF → 0x0A); `measure_tier_funnel.py` production-gate replacement (bind_source_text + prepare_tier0_plan, CID leg inherited by funnel); `audit_tier_coverage.py` production admission calls (`admit_show_wrappers`, `admission_verdict`); `census_show_shapes.py` promoted with `--pages` sampling; S4/S5 Step 0 measurements (run-binding 48.3 % aggregate PASS, word-fragment 20.1 % aggregate PASS / 8.5 % on CJK fixture FAIL — S5 follows S4); docs `PITFALLS.md` entries for operator-gate masking, bare EOL, audit staleness, font-resource collision, q/Q scoping, pixel quantization, whitespace skipping; PITFALLS_INDEX regenerated (367 entries). S0 review fold landed (census tests in-process, audit verdict order = production order with PAGE_GEOMETRY_UNSUPPORTED first, census CLI guards/privacy/close, shared `PageReplay.wrappers_for` + `transforms.page_visual_frame_or_none` chokepoints, funnel plan stage on `prepare_plan(max_tier=0)` with per-document ReplayEvidenceCache) and S0-b (page-scoped font lookup in DocumentFontRegistry) landed red-first. S0 fold 2: verify.py page-scope fix, instrument memoisation, ARCHITECTURE and Step 0 pitfalls landed. S0 fold 3 (2026-09-07, from seven finished review-finder reports after the reviewer itself was rate-limited): census reads `/DescendantFonts` and `/Differences` through the production parsers and gives kern-only `TJ` arrays their own `items=0` class; audit reports the quote operators as `unsupported_show_operator` (production order); funnel buckets palindromes before bind and asks `prepare_plan` on frame-unprovable pages instead of mirroring the gate; stale pitfall fix references corrected; hygiene follow-ups registered in plan §8.6 (PITFALLS_INDEX: 371 entries).

**S1 landed 2026-09-08:** the operator gate now admits a single-item `TJ` (at both emission sites, including the CID leg's hex-only scope) and a `render_mode == 2` synthetic-bold show behind a PROVEN stroke pen (`plan.tier0_show_gate`, `_prove_stroke_pen`); a leading kern before the one admitted item, a re-lex failure, and a multi-item array each get their own code (`TJ_LEADING_KERN_UNPROVEN`, `TJ_ITEM_RELEX_FAILED`, `TJ_MULTI_ITEM_ARRAY`) rather than sharing `NOT_SINGLE_LITERAL_TJ`; mode 1 and modes 4-7 stay refused structurally, mode 3 (invisible) is refused only until S7, and an unprovable or too-wide stroke pen refuses `STROKE_BOUND_UNPROVEN`/`STROKE_BOUND_TOO_LARGE`. Measured on office-report-23p (2237 shows): `not_single_literal_tj` is gone from both instruments and `plan_survivors` is still **0** — the dominant refusal moved to `mc_wrapper_not_pure_layer` (audit 1959/2237 = 87.6 %, funnel plan stage 133/180 = 73.9 %) alongside `tj_multi_item_array` (audit 278/2237 = 12.4 %, funnel 47/180 = 26.1 %), confirming S1 and S2 must land together exactly as predicted. The S2 dependency is demonstrated on both fixtures, by different instruments: the funnel/audit numbers above for office-report-23p, and — since neither instrument has a page-selection flag for the 50-page CAD fixture — a dedicated fixture-pins module (`test_scripts/test_text_commit_s1_fixture_pins.py`) for CAD, which found all ten of the fixture's single-item bold targets sitting inside a struct-content wrapper (not the fixture's `/OC` layers) and refusing `mc_wrapper_not_pure_layer` too. A same-day, two-reviewer review fold found and fixed nine defects in the landed slice (an ExtGState/`w` pen-resolution ordering defeat, an undefined-join/sub-minimum-miter-limit admission gap, a malformed-operand read as "unchanged", a `page_fingerprint` gap over the ExtGState table, a missing twin-side stroke outset at the duplicate-painter gate plus its own ordering fix, a mislabelled Tier 1 splice kind, and two instruments double-counting an admitted shape) — full write-up in `plans/task16-4-glyph-coverage-expansion.md` §8.7 and `docs/ARCHITECTURE.md` §10.1.8; the docs-agent failure note from the interrogation round is not repeated here (process, not project).

**F6 closure 2026-09-20:** an independent Astra medium peer rechecked all
nine S1 review items; 391 targeted S1/review tests, Ruff, and mypy passed,
with no code changes required. The known full-suite Qt printing failure
remains unclaimed and is tracked under T16-6.

**S10 landed 2026-10-23:** a page whose /Annots array holds an inline annotation dictionary (no indirect reference; PyMuPDF `page.annots()` raises `AttributeError` on it) is now refused with `annotations_not_indirect` in `prepare_plan` (with backstops in `TieredCommitEngine.prepare`, `commit` and the plan preview) instead of the error escaping the engine. One strict reader (`inspect.annotation_entries`, `require_indirect_annotations`, `InlineAnnotationError`); `page_fingerprint` stays total (the `first_widget`/`next` walk in `_widget_entries` is guarded by `except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase)`, every widget row falling back to a `(0, 0, 0, 0)` rect, so a widget /Parent cycle cannot raise out of it) and no longer collides two inline annotations; `require_indirect_annotations` types an unreadable `annot_xrefs()` read as `InlineAnnotationError`, so correctness does not rest on the widget gate running first. Indirect pages and inline Link/Popup pages are unchanged. The rebuild is not offered for it. Plan: `plans/task16-4-glyph-coverage-expansion.md` S10.

- [ ] `model/tools/annotation_tool.py` `get_all_annotations` and `toggle_annotations_visibility` iterate `page.annots()` unguarded and raise on a page with an inline /Annots dictionary (annotation panel); give them the same typed handling or a guarded read.
- [ ] `annotations_not_indirect` is not gated in the model: `pdf_text_edit.edit_text` sends any tiered refusal with `allow_rebuild=True` (including the consented cross-page move) to the legacy rebuild, and only the View's rebuild button is hidden (`_NOT_REBUILDABLE`). Restyle, drag, delete and multiline edits on such a page surface an earlier, rebuildable code. Hiding the button is a conservative fail-closed choice: `_save_overlapping_annots` cannot snapshot inline dictionaries, but annotation loss from `apply_redactions` has not been shown (a probe with the production redaction flags kept inline Square, Text and FreeText annotations). Owner decision: extend the `pdf_model.edit_text` hard-reject boundary to this code, or leave it.
- [ ] An INDIRECT annotation with no `/Rect` makes `prepare` refuse with `verification_failed: annotations changed` (`annot.rect` reads `(2147483520, 2147483520, 2147483520, 2147483520)` before the content-stream write and `(2147483520, 2147483520, -2147483648, -2147482624)` after; the annotation object is unchanged, and HEAD reads the same). A safe negative under a misleading code, and the rebuild is offered for it. Follow-up: normalise degenerate rects in `inspect._walk_annotation_rects`, or refuse a listed annotation with no `/Rect` under a page-shape code.

### T16-6 — Test suite has no hang protection (register only, found 2026-09-05)

`pytest-timeout` is not installed, so a test that opens a modal or deadlocks
stalls the whole 30-minute run with no output (seen twice during T16-3: a real
`PDFView` fixture blocking on the consent dialog, and a Qt abort in
`test_page_reorder.py` when a second pytest ran concurrently). Interim
mitigation that works today: `-o faulthandler_timeout=300` dumps the stuck
stack. Proper fix: add `pytest-timeout` to the dev extras and a per-test
`timeout` in `pyproject.toml`; run full suites one at a time.

### T16-5 — Lossy font token on the protected-span replay path (register only)

Not the cause of the reported 標楷體→Sans (the **main** edit path preserves the
font — `pdf_text_edit.py:570` uses `_resolve_add_text_font` correctly, and both
repros kept `DFKaiShu-SB-Estd-BF`), but proven lossy on its own:
`_replay_protected_spans` (`pdf_text_edit.py:344→359`) pre-resolves through
`_resolve_font_for_push`, which collapses any unrecognised CJK name to `"helv"`;
`_resolve_cjk_companion_font` then yields `china-ss` and **no `@font-face` is
emitted at all**, so MuPDF falls back to its built-in sans. Probe: hint
`DFKaiShu-SB-Estd-BF` → `src: url("C:/Windows/Fonts/kaiu.ttf")`; hint `helv` →
no rule. Fix = thread the raw span font name, never a push-resolved token. The
user-visible Sans rendering was **not** reproduced on the main path and still
needs the exact GUI selection to pin down.


### 2026-09-06 Astra interrogation of T16-4X

- [x] Remove the audit's speculative Tier 1 category and duplicate predicate /
  reason ladder; keep two structural counts and update the benchmark consumer.
  Red tests prove TJ arrays refuse at both tiers and Type0 literal strings
  cannot count as eligible. Keep the S0 lexer/font-scope fixes and verifier.
- [x] Correct T16-4X's Tier-0-only completion premise and remove its obsolete
  model-specific orchestration. The proposed slices remain unfinished.
- [ ] Full recursive corpus coverage remains unproven: inventory is 2,933
  PDFs (11 root, 32 sample-files, 3 Test-PDF-Files, 2,887 veraPDF). Account for
  every file, safe refusal and unmeasured case; measure real edits through
  preview/commit/undo/redo/save/reopen, including the existing Tier 1 path.
  Five-fixture production rerun: 1,220 sampled targets, 487 bound, 235
  palindrome probes skipped, 252 attempted plans, zero accepted (251
  `not_single_literal_tj`, one `mc_wrapper_not_pure_layer`). This is evidence
  of remaining work, not a full-corpus result or a new production regression.
