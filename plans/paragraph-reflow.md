# Paragraph reflow for growing text edits (F14-VF4-WRAP-REFLOW)

Plan only (owner request 2026-10-12). Nothing in this file is built; shrink / refuse
(`_right_neighbour_limit`, `_wrap_floor`, `_new_text_overprints` in `model/pdf_text_edit.py`)
stays in code until the owner approves a slice. Branch at planning time: `feat/true-text-edge-cases`.
Revised 2026-10-13 to agree with the owner answers (Q1 and Q4 changed the design; Q2, Q3, Q5, Q6, Q8,
Q10 confirmed the defaults and got dedicated red-first tests in section 7.1).
Related: TODOS `F14-VF4-WRAP-REFLOW`, `F13-VF-4b`; PITFALLS `F13-VF-4`, `F14-VF4-WRAP`,
`F14-VF4-OVERLAP`, `F15-VF4OV-DIAGONAL`, `F15-VM2-RTL`, `F15-RTL-ORDER`, `F13-VF-3`, `F13-VF-2`.

Owner decisions already taken (not questions):
1. A growing edit reflows the rest of its line and the following lines of the same paragraph instead
   of being shrunk or refused; content outside the paragraph stays pixel-identical.
2. A wrap at the right-hand neighbour may break a word at a typed hyphen (`Two-` / `Column`).
3. A longer right-to-left word keeps its RIGHT edge fixed and grows to the left.

Vocabulary: "reflow" here is paragraph re-wrapping. It is NOT `EditTextCommand.reflow_fn` /
`CommitOutcome.allows_external_reflow` (the Track A/B block-displacement hook, no production
wiring since Task 12 step 7, `docs/ARCHITECTURE.md` §10.1). The hook is left alone.

## Goal

When the text a user types into one run (or a paragraph-mode selection) is wider than the room
before the next run on its line, the consented rebuild re-breaks that line and the following lines
of the same paragraph, keeping every line's start, baseline and alignment, and leaves every glyph
outside the paragraph where it was. Tier 0 / Tier 1 keep their "no neighbour moves" contract and
refuse as today. Fit is decided BEFORE any mutation. A reflow that does not fit the free space below
the paragraph is neither refused silently nor pushed down (owner Q1): the model raises a zero-mutation
`REFLOW_DOES_NOT_FIT` (a code of its own, so the Controller can tell it from the plain
`TEXT_DOES_NOT_FIT` error), the typed text stays in the editor, and the Controller offers the user, in
zh-TW, "enlarge the box manually" or "cancel"; cancel changes nothing. Never a rollback. Redrawn text is still substitute-font text (the
existing disclosed degrade of the rebuild, PITFALLS F13-VF-3 / T16-5); the original-font variant
is the deferred Tier 2R (section 10).

## Measured facts (read-only probes on copies, PyMuPDF 1.27)

- `test_files/sample-files-main/011-google-doc-document/google-doc-document.pdf` p1: the index
  gives ONE `EditableParagraph` (`pg0_b1_p0`, 19 visual lines, 137 word runs, ArialMT 11 pt Type0
  subset, leading 14.55, ragged left). Every line ends far short of the widest line (measure 408 pt;
  line 1 ends at 206.84), i.e. every line break is a HARD break (Zen of Python, one sentence per
  line). Stream shape: 1045 `Tj` + 1045 `Td` (one show per word). Corpus case `better` ->
  `better-than-ever` (PITFALLS F14-VF4-WRAP) has 200 pt of free room on its own line; it is refused
  today only because the flush neighbour `than` is a wall.
- `test_files/sample-files-main/026-latex-multicolumn/multicolumn.pdf` p1: `pg0_b4_p0` = 34 visual
  lines but 44 PyMuPDF lines (some split at a `Td` on the same baseline), 251 runs, CMR10 9.96 pt,
  JUSTIFIED (non-last lines end at 300.65..300.71), a first-line indent (x0 81.96 vs 72.0) that
  marks a second paragraph the index merged into the same `EditableParagraph`, 9 lines end in a
  TeX hyphen (`adip-` / `iscing`). Stream shape: 74 `TJ` (one per line, word gaps as kern items),
  1 `Tw`. The title `pg0_b0_p0` (`Two-Column Document with Lorem Ipsum`) is one centred line.
- `insert_htmlbox` IGNORES `word-spacing` and `letter-spacing`; `text-align: justify` works only
  for non-last lines of a block, so a one-line box is never justified. Justified lines must be
  placed word by word.
- Re-break simulation on `pg0_b4_p0` with the ORIGINAL glyph widths, editing `ipsum` on line 3:
  a 4 pt growth re-breaks 2 lines and converges (line 5 starts with its original word on its
  original baseline); a 30 pt growth (`ipsum-lorem`) rewrites 18 lines before converging. These
  counts PREDATE Q4: that run used the old D6 soft-hyphen rule (the nine TeX line-end hyphen pairs
  rejoined as `adipiscing`, the hyphen re-inserted only where a break fell). If the halves are not
  rejoined at all (`adip-` and `iscing` as two words) the paragraph never converges and shows
  `adip- iscing` fragments. With Q4 the halves are rejoined and the hyphen is KEPT (D6): the rejoined
  token is `adip-iscing`, one hyphen wider than `adipiscing`, so convergence is rarer than the figures
  above and the hyphen can print mid-line. Slice 0 re-runs the simulation with hyphens kept and records
  the new counts; they are not asserted.
- The controller's consent text already says "字型、字距或相鄰排版可能改變（降級提交）"
  (`PDFController._fallback_confirmation_message`, reached through the model's `confirm_fallback`
  callback): neighbour movement is inside the existing consent. (An earlier draft named
  `_ask_rebuild_consent`; no such function exists.)

## Affected modules

| Module | Change |
|---|---|
| `model/text_reflow.py` (new, Qt-free, no page mutation) | `ParagraphLines`, `ReflowToken`, `ReflowLine`, `ReflowPlan`; `paragraph_lines(model, page_idx, paragraph)`, `detect_layout(lines)`, `tokenize_lines(...)`, `break_lines(...)`, `plan_reflow(...)`. |
| `model/pdf_text_edit.py` | `edit_text` consented branch: new `_reflow_needed` (section 4.3), compute the plan after the tiered refusal, `_widen_resolve_for_reflow`; `_apply_redact_insert_body`: new reflow branch before `_classify_insert_path`; `_verify_rebuild_edit`: reflow postconditions; new `_column_floor` (section 4.4); `_replay_protected_spans` / `_protected_span_drawn_in_place` gain an `offset`; `_rebuild_glyph_loss` over the widened member set. |
| `model/edit_requests.py` | `ReflowPreview` DTO (moved runs: `run_id`, old rect, new rect, new text) -- the allowlisted View DTO module (`view-no-model` `ignore_imports` in pyproject.toml). |
| `model/pdf_model.py` | thin delegates (`plan_text_reflow`, `reflow_preview_for`), `_resolve_paragraph_candidate` reused. |
| `model/text_edit_refusal.py`, `controller/text_edit_refusals.py` | new refusal code `REFLOW_DOES_NOT_FIT` (the twin of `DRAGGED_BOX_OVERPRINTS`) and its zh-TW sentence; the plain `TEXT_DOES_NOT_FIT` sentence has no offer and stays for the non-reflow paths. |
| `controller/pdf_controller.py` | `_fallback_confirmation_message`: add the line count, 「將重排 N 行」 (Q5); `_offer_enlarge_box` in the `except` branch of `_commit_text_edit` (the twin of `_offer_place_anyway`); forward `ReflowPreview` to the view. |
| `view/message_boxes.py` | `confirm_enlarge_box(parent, message)` (the twin of `confirm_place_anyway`): two buttons, proposed labels 「手動放大文字框」 and 「取消」; default and Esc are 「取消」. |
| `view/text_editing.py` (`PreviewRenderer`) | draw the moved runs as ghosts from the DTO (Slice 3). |
| `test_scripts/test_text_reflow.py` (new), `test_scripts/test_edit_text_helpers.py`, `test_scripts/test_reflow_controller.py` (new, Qt offscreen) | red-first tests; existing F13-VF-4 / F14-VF4-WRAP expectations that flip (section 7.2). |
| `scripts/census_paragraph_shapes.py` (new, Slice 0) | corpus census: alignment class, hard/soft breaks, stream shape per paragraph. |
| `docs/ARCHITECTURE.md`, `docs/PITFALLS.md` + index, `docs/FEATURES.md`, `TODOS.md` | per slice. |

## Decisions

- D1 Reflow lives in the consented rebuild only. Tier 0 (`_build_tier0`) and Tier 1 (`_build_tier1`,
  `verify_tier1_commit`) are single-show patches whose verifier proves no neighbour moved
  (`GROWTH_REGION_NOT_BLANK` glyph count + raster gate); moving neighbours is a different contract.
  They refuse exactly as today (`ADVANCE_MISMATCH` -> Tier 1 -> `GROWTH_REGION_NOT_BLANK`, or
  `MULTI_SPAN_TARGET` for a paragraph-mode target). Without `allow_rebuild` the edit is `REJECTED`
  with zero mutation, as today.
- D2 The plan is computed before any mutation, from the index and one measurement pass, so "does not
  fit" is known while the page is still untouched: no rollback, and (owner Q1) no discarded text. The
  model raises `TextEditRefused(REFLOW_DOES_NOT_FIT)` with zero mutation, BEFORE the rebuild consent
  is asked (nobody consents to a rebuild that cannot happen). The code is new and distinct from
  `TEXT_DOES_NOT_FIT`, exactly as `DRAGGED_BOX_OVERPRINTS` is distinct, because the Controller must
  recognise it: reusing `TEXT_DOES_NOT_FIT` would fall into the plain `show_error` path. The Controller
  (`_offer_enlarge_box`, the twin of S17's `_offer_place_anyway`) then offers, in zh-TW, 「手動放大文字框」
  or 「取消」 (labels proposed). The typed text stays in the editor in both cases (`_last_edit_result`
  stays None, so the View keeps the editor, as for a cancelled S17 offer). Both answers are zero
  mutation -- no command, no undo step, no page byte, no `pending_edits` entry -- and differ only in the
  UI: "enlarge" returns to the kept editor for the user to resize or drag the box, and the next Apply is
  then a dragged `new_rect` edit (D21); "cancel" simply returns, and the user's own Esc ends the editor.
- D3 Visual lines are the paragraph's runs clustered by baseline (`origin.y` within 0.3 em,
  `_units_share_a_baseline`), never by `line_idx` (PyMuPDF opens a line at every `Td`; `pg0_b4_p0`
  has 44 of them for 34 visual lines). Reading order inside a line: `span_idx` (F15-RTL-ORDER).
- D4 Hard breaks are inferred: line i ends with a hard break when `measure - x1(i)` is at least the
  width of line i+1's first token plus one space (the next word would have fitted but was not put
  there), or when line i+1 starts with a different indent than line i's successor pattern (first-line
  indent = new paragraph), or when line i is the paragraph's last line. A hard-break line is a
  reflow unit of its own: its overflow goes to an INSERTED line (section 4.3), never into the next
  line's words. A line that ends with a line-end hyphen is never a hard-break line: its break is the
  typesetter's hyphenation break and its last token continues on the next line (D6, Q4). In
  `google-doc-document.pdf` every line is a hard break, so `better-than-ever` touches one line.
- D5 Measure = max `x1` over the paragraph's lines (justified: that shared edge). When the edited
  line IS the widest line, or the paragraph has at most two lines, max `x1` says nothing about the
  column width; the measure then falls back to the nearer of `_right_wall` and the left edge of the
  nearest non-member run in the band (Q10, owner-confirmed). A single-line paragraph: `_right_wall`.
  A centred single-line paragraph keeps its start x and baseline and grows to the right (Q3,
  owner-confirmed); the breaker never re-centres. Left edge per line is its own `x0` (the first-line
  indent survives); baselines of existing lines are kept exactly; inserted lines continue the median
  leading (`_rebuild_insert_markup`'s `_line_ht` rule).
- D6 Break opportunities: a source space or an inter-run gap wider than 0.2 em (TeX inter-sentence
  gaps have no space character: `elit.` / `Ut` are two runs); after an existing `-` (U+002D) or
  U+2010 inside a token (owner decision 2, the shipped D-HYPHEN-WRAP rule: U+2011 never breaks, no
  hyphen is ever inserted, a hyphen that OPENS a word is glued to it so a line is never just `-`);
  between CJK characters, except before closing punctuation (、。，」）]!?) and after opening
  punctuation (「（[); never inside a Latin word. Line-end hyphens (owner Q4, which overrode the
  soft-hyphen default): a hyphen that ends an ORIGINAL line is a CHARACTER and is always kept, never
  dropped on rejoin. The last token of that line and the first token of the next line are joined
  WITHOUT a space into one token that keeps the hyphen (`adip-` + `iscing` -> `adip-iscing`, `Two-` +
  `Column` -> `Two-Column`), whatever case the continuation starts with; the only break opportunity
  inside it is the ordinary one after the hyphen. A standalone dash (a `-` preceded by a space) is
  its own token and joins nothing. Consequence, stated plainly: a hyphen that exists only because TeX
  hyphenated the word at a line end stays printed when the rejoined word no longer sits at a line end,
  so a rejoined `adip-iscing` prints with a visible hyphen mid-line (a reader expects `adipiscing`
  there) and, when it must break again, breaks only after that hyphen. The page text is never
  "corrected", only re-broken.
- D7 Convergence: re-breaking stops at the first re-broken line that starts with the same token on
  the same baseline as an original line; every later line is untouched (not redacted, not redrawn).
  Convergence is best effort (section 2: 2 lines for a 4 pt growth, 18 lines for 30 pt, both
  measured before Q4). There is no cap on the number of redrawn lines (Q8, owner-confirmed); the
  consent dialog discloses it in the fixed zh-TW phrase 「將重排 N 行」 (Q5, owner-confirmed), N =
  re-broken original lines + inserted lines.
- D8 Growth below the paragraph: an inserted line may use free space down to `_column_floor`
  (section 4.4). When the tail would pass it, `plan_reflow` reports `does_not_fit` and the edit ends in
  the Q1 outcome of D2 (typed text kept, offer "enlarge the box manually" / "cancel", zero mutation).
  Nothing outside the paragraph is pushed (owner rule "pixel-identical outside the paragraph"; Q1
  answered that the next block is never pushed down either) and nothing is shrunk to make it fit.
- D9 Token widths are measured in the font the draw path will use (one scratch render per edit,
  `_htmlbox_reference` style, plus `fitz.Font.text_length` for `insert_text` tokens), never in the
  original font: the breaker must agree with what is drawn (PITFALLS OD-UNI1-COMMIT rule). Original
  widths (rawdict char boxes) are used only for hard-break inference (D4) and layout detection.
- D10 Justified lines: every full re-broken line distributes `measure - natural width` evenly over
  its gaps; the last line of the paragraph (or before a hard break) stays ragged. Justified lines are
  drawn token by token (D11); ragged lines are drawn as one nowrap placement per run of same-style
  tokens.
- D11 Drawing: Latin-1-safe tokens via `insert_text_page_space` at the computed origin (no probe);
  everything else via `_place_htmlbox_at_origin` + `_insert_htmlbox_unshrunk` (F13-VF-3 machinery,
  `_NO_WRAP_CSS`); the whole insert stays inside `font_compaction_scope`. A CJK line is placed as
  one nowrap string per style run unless justified.
- D12 Right-to-left (owner decision 3): a line whose runs `contains_rtl` reads right to left; the
  line start is its right edge, "the rest of the line" is the runs to the LEFT, which shift left;
  the wall is the paragraph's left measure. A line mixing strong directions (digits or Latin inside
  Hebrew) refuses reflow and falls back to today's behaviour. 180-degree blocks reuse
  `_block_reads_right_to_left`. Tier 0 already sends every RTL edit to the rebuild
  (`_tier0_target_from_resolve` returns None), so reflow is the RTL growth path.
- D13 Vertical text (rotation 90/270, `is_vertical`) is out of scope: today's vertical branch
  (`_vertical_html_rect`, `_binary_shrink_height`; TODOS F13-VF-4b) is unchanged.
- D14 Mixed fonts / sizes / colours in one paragraph: each token carries its run's `font`, `size`,
  `color`; the typed text carries the edited run's style (or the request's `style_overrides`);
  widths are measured per token in its own substitute font; `_build_multi_style_html` is reused per
  placement. The line's baseline is the run baseline, so a larger run keeps its baseline, not its
  box top.
- D15 Protected neighbours: the reflow band = the union of `touched_lines` (the edited line
  through the last RE-BROKEN line; the converged line and everything after it are outside the
  band). The overlap cluster is recomputed on the band; non-member runs that intersect it (a watermark, another block's
  superscript, an overlap textbox) are `protected_spans` and are replayed in place exactly as today;
  the overprint guard `_new_text_overprints` stays the chokepoint with `exempt` = protected spans
  only (never the reflowed members' old boxes). A same-line non-member run (another table cell cut
  by `_split_line_into_cells`) stays a wall: cells never reflow into each other.
- D16 A replacement that is not wider than the room before the wall, a shorter one included, does
  not reflow: no plan is computed, the gap stays and today's path runs unchanged (Q2,
  owner-confirmed).
- D17 Reopen anchor: the run-mode anchor of an edited word that moved to another line is migrated by
  `_choose_anchor_run` onto the rebuilt run that holds the new text; when the word was split across
  lines the anchor is dropped (never planted on one half).
- D18 Paragraph-mode edits (`target_mode="paragraph"`) route through the same breaker: the old and
  new paragraph texts are diffed token-wise, the first changed token picks the first re-broken line,
  unchanged leading lines are not redrawn. This replaces the one-box MuPDF re-wrap for paragraphs
  and fixes the lost first-line indent (Q6, owner-confirmed).
- D19 After a reflow the page is a legacy-rewritten page: `pending_edits` / the
  `pending_page_maintenance` gate and the Tier 0 refusal on such pages behave as for any consented
  rebuild (part-5 blocking defect 1 is a separate plan).
- D20 (verified by an in-memory probe of the fixtures) a flush same-line run is a paragraph member
  by construction: `_neighbour_pdf`'s `NEXT` (10 pt, red, gap 0 or 40 pt) lands in `ab`'s paragraph
  `pg0_b0_p0` because rule (a2) re-joins same-baseline units below 3.0x the size. So the F13-VF-4
  "wall" survives only for a run that is NOT a member: a cell cut by rule (a) inside ONE PyMuPDF
  line (same font and size, gap between 0.8x and 3.0x the size, e.g. `ab` + 20 pt + `NEXT` at
  14 pt), or a run further than 3.0x away (which never walled anything). The F13-VF-4 tests keep
  their invariants on such a cell fixture and get reflow twins on the member fixture (section 7.2).
  Owner-confirmed (Q9): member runs on the edited line move with the edit.
- D21 A dragged edit (`new_rect`, same page or cross-page) never enters the reflow branch: it follows
  S17-DRAG-GUARD (overprint-guarded, never capped, a per-edit "place anyway") and the owner's drag
  offer of 2026-10-13, "move to nearest free spot / place anyway / cancel", for same-page and
  cross-page drops; Q1's "enlarge the box manually" lands here, because the enlarged box is a dragged
  `new_rect` edit. The existing `test_s17_*` tests stay the guard.

## Design

### 4.1 Paragraph model (`model/text_reflow.py`)

`paragraph_lines(model, page_idx, paragraph)` -> `ParagraphLines`: for the `EditableParagraph`
(`model.block_manager.find_paragraph_for_run`), its runs grouped into visual lines (D3), each line
with `x0`, `x1`, `baseline`, `runs` in reading order, `right_to_left`, `indent` (x0 - column x0),
and per-run character boxes from `PDFModel.get_chars_in_run` (CJK runs are tokenised per character).
`detect_layout(lines, edited_line, wall_candidates)` (`wall_candidates` = `_right_wall` and the left
edges of non-member runs in the band, used only for the Q10 fallback of D5) returns `alignment` in
{left, right, centre, justify} (justify: all non-last lines end within 0.5 pt of the measure and at
least one line's gaps differ from the natural space), the `measure`, the median leading, and
`hard_break[i]` per D4.

### 4.2 Breaker

`tokenize_lines` turns the lines from the edited line on into `ReflowToken`s (text, width, style,
break kind, origin line; a line-end-hyphen pair is ONE token that keeps its hyphen, D6); the edited
run's tokens are replaced by the tokens of the new text, split by the same `_char_kind` rules as the
index. `break_lines` is greedy first-fit per
reflow unit (a hard-break unit ends at its hard break), with the per-line `x0` of the original line
when the line index exists and the column `x0` for inserted lines, and the break opportunities of D6.
Output `ReflowLine`s carry token placements (x along the baseline, y) with justification applied
(D10); RTL lines are laid from the right edge leftwards (D12). `plan_reflow` applies D7 and returns a
`ReflowPlan`: `touched_lines` (original line indices to redact), `new_lines`, `untouched_tail`,
`inserted_count`, `grows_to_y1`, `moved_runs` (for the preview DTO). It returns a reason
(`does_not_fit`, `mixed_direction`, `vertical`) instead of a plan when it cannot. `mixed_direction` and
`vertical` fall back to today's path; `does_not_fit` stays an internal reason of the planner, and the
model turns it into `REFLOW_DOES_NOT_FIT` (D2, the Q1 offer), never into shrink or push-down. The typed
text is input only: the planner never consumes or alters it.

### 4.3 Where it runs (`edit_text`, consented branch)

Order matters: the member set must NOT be widened before `_attempt_tiered_commit`, or
`_tier0_target_from_resolve` returns None for multi-line members and Tier 0 dies for edits that
commit in place today.

1. `_resolve_edit_target` (unchanged) -> tiered attempt -> refusal as today.
2. `allow_rebuild`: `plan = plan_reflow(...)` only when `_reflow_needed(model, page_idx,
   resolve_result, new_text, size)` says so: `new_rect is None`, not vertical, and the new text's
   width in the draw font exceeds the room before the wall. `_reflow_needed` is a new helper that
   reproduces `fast_available_w` (`_right_wall` on the edited runs' extent, `fast_margin`) and
   `_right_neighbour_limit` on the UN-widened resolve result; today those are locals of
   `_apply_redact_insert_body`, which after step 3 would see a multi-line extent and a different
   wall. `_apply_redact_insert_body` keeps computing its own locals for the non-reflow path. When
   the text fits before the neighbour, no reflow (today's fast path); the same holds for a
   replacement that is shorter or equal (Q2): no plan is computed. When `plan_reflow` reports
   `does_not_fit`, raise `TextEditRefused(REFLOW_DOES_NOT_FIT)` here -- before step 3 widens anything,
   before the consent is asked, with the page untouched (D2, D8, Q1).
3. If a plan exists: `resolve_result = _widen_resolve_for_reflow(resolve_result, plan)`: members =
   edited run + every run of `touched_lines`; cluster and `protected_spans` recomputed on the band
   (D15); `redact_rect` = band union.
4. `_rebuild_glyph_loss(new_text, resolve_result)` over the widened set, so the consent names
   unkeepable glyphs in reflowed lines too (F11-UNI-1); `pending_chain` gets `legacy:reflow`; the
   model hands the line count N to the consent callback next to `glyph_loss`, and
   `_fallback_confirmation_message` says 「將重排 N 行」 (Q5; counts only, like the glyph-loss line).
5. `_apply_redact_insert(... reflow_plan=plan)` -> `_verify_rebuild_edit(... reflow_plan=plan)`.

### 4.4 Execution (`_apply_redact_insert_body`, new branch before `_classify_insert_path`)

- Floor: `_column_floor(page, band, x0, x1, paragraph_run_ids)` = top of the nearest untouched glyph
  below the paragraph inside the column, read from the pre-redaction dict minus the paragraph's own
  runs, INCLUDING blocks `_push_down_can_move` would move (D8). `_wrap_floor` is not reused: it
  deliberately excludes movable blocks because the old path pushes them. `plan_reflow` has already
  compared `grows_to_y1` with this floor; the body re-checks and, on a mismatch, raises
  `REFLOW_DOES_NOT_FIT` (the same Q1 outcome) before touching the page.
- Redaction: `_redact_owned_glyphs` over the glyphs owned by the touched lines' runs only
  (`_glyphs_owned_by_runs`); `survivors` / `lost_foreign` refuse as today.
- Protected replay in place (today's `_replay_protected_spans`).
- Placement per D11, per `ReflowLine`, through the existing `_page_glyphs` before/after and
  `_refuse_if_overprinted` (exempt = protected spans).
- Return value: the edited run's new rect for the reopen anchor (D17); the block's `layout_rect`
  union of the new lines.

### 4.5 Verification (`_verify_rebuild_edit`, additions when a plan is present)

- Presence: every `ReflowLine`'s text present in the band (`_presence_norm`), the edited text present.
- Geometry: each line's start glyph lands on its planned start (texttrace, `_start_point` rule,
  tolerance 0.3 pt = `_GLYPH_MATCH_TOL`); justified lines end within 0.5 pt of the measure.
- Outside the band: `_page_glyphs` before/after identical in text and origin for every glyph outside
  the band that is not a replayed protected span; the `untouched_tail` lines identical.
- Any failure: `_rollback_rebuild_page` + `_RebuildRolledBack` with the existing codes
  (`TARGET_NOT_PRESENT`, `PROTECTED_SPAN_CHANGED`, `VERIFICATION_FAILED`).

### 4.6 Tier participation summary

| Path | Behaviour with reflow |
|---|---|
| Tier 0 | unchanged: refuses growth (`ADVANCE_MISMATCH`), paragraph/multi-line (`MULTI_SPAN_TARGET`). |
| Tier 1 | unchanged: kern-compensated transplant; a flush neighbour refuses `GROWTH_REGION_NOT_BLANK`. |
| Consented rebuild, fast `insert_text` path | unchanged when the text fits; else the reflow branch (4.4). |
| Consented rebuild, htmlbox route | reflow branch replaces strategy A/B/C and the wrap floor for a reflowable edit; A/B/C stay for dragged `new_rect`, vertical text, and non-reflowable cases (mixed direction, table cells). A reflow that does not fit does NOT fall back to A/B/C, shrink or push-down: it ends in the Q1 offer (D2, D8). |
| Dragged edit (`new_rect`, same page or cross-page) | never reflows (D21): S17-DRAG-GUARD (guard, no cap, per-edit "place anyway") plus the owner's 2026-10-13 offer "move to nearest free spot / place anyway / cancel"; Q1's "enlarge the box manually" re-enters here. |
| Protected neighbour replay | in place, unchanged; `offset` parameter added for Slice 1 same-line shift. |
| Rotated page (`/Rotate`) | nothing new: `edit_text` works in unrotated space; tests on a /Rotate 90 fixture. |
| 180-degree lines | reading order flipped via `_block_reads_right_to_left`. |
| Vertical (90/270) | refuses reflow, today's path. |
| RTL | D12. CJK | per-character tokens, kinsoku (D6). Justified | D10. Mixed fonts | D14. |
| Undo / redo | unchanged: the consented rebuild records the page before-snapshot and an after-snapshot (`EditTextCommand._capture_after_snapshot`); a multi-line rewrite is one command. |
| Save / reopen | unchanged: `font_compaction_scope` dedupes the htmlbox fonts; `save_as` / incremental paths untouched. |
| Signed documents / widgets | unchanged: under the shipped default `PDFModel.edit_text` refuses before any engine (`if self.text_commit_settings.engine == "tiered"`: `page_has_widgets_or_signatures`, `document_has_a_signed_signature`, `REJECTED_UNSUPPORTED`), so reflow never runs on them; the `engine=legacy` kill switch bypasses that gate for a reflow exactly as it does for every rebuild today. |
| Secure-latched session | unchanged: measurement and placement probes use in-memory `fitz.open()` scratch docs; no temp files. |

### 4.7 Preview

The plan preview (`model/text_commit/preview.py`) is Tier 0/1 only and is untouched. For the
rebuild path the view's `PreviewRenderer` draws only the edited text today. Slice 3 adds
`ReflowPreview` (DTO in `model/edit_requests.py`), produced by `PDFModel.reflow_preview_for(...)`
(the same `plan_reflow`, no mutation), handed View-ward through the Controller, and drawn as
translucent ghosts of the moved runs. Until Slice 3 the preview shows the edited text only and the
consent dialog is the disclosure.

## Steps (slices; each ships on its own)

**Slice 0: breaker + census (no product change).** `model/text_reflow.py` with red-first unit tests
(section 7.1); `scripts/census_paragraph_shapes.py` run over the local corpus and the sample files,
table pasted into the Log. Acceptance: tests green; the census lists per paragraph its alignment,
hard-break count, and stream shape (Tj-per-word+Td / TJ-per-line / other); the original-width
re-break simulation of section 2 is re-run with line-end hyphens kept (Q4) and its line counts are
recorded in the Log (not asserted).

**Slice 1: same-line reflow.** The edited line only (no inserted line, no following lines): the
right-hand members of the same paragraph line shift by the growth (`_replay_protected_spans` with
`offset`), measured in the draw font, limited by the measure (D5). When the shifted line would pass
the measure, Slice 1 has no second line to wrap into: the plan reports `does_not_fit` and the edit
ends in the Q1 outcome of D2 (`REFLOW_DOES_NOT_FIT`, typed text kept, offer "enlarge the box
manually" / "cancel", zero mutation); it does not fall back to shrink, the wrap floor or push-down
for a reflowable edit. Slice 1 therefore also carries the Q1 plumbing (the refusal code and its zh-TW
sentence, `_offer_enlarge_box`, `confirm_enlarge_box`), since it is the first slice that can report
`does_not_fit`. Slice 2 adds the wrap inside the paragraph, so the same outcome then arises only when
the inserted lines pass `_column_floor`. Dragged edits stay out of the reflow branch: they follow
S17-DRAG-GUARD and the 2026-10-13 drag offer (D21). Acceptance: synthetic
`test_reflow_shifts_the_rest_of_the_line_by_the_growth` on a fixture whose paragraph has a line
WIDER than the edited one (so the measure is known; `_same_block_pdf`'s edited line is its widest
line and only flips in Slice 2) -- SUCCESS, no overprint, next line of the same block identical,
neighbour at its baseline and size; corpus `google-doc-document.pdf` p1
`better` -> `better-than-ever` SUCCESS on one line, every other line of the page zero-diff at 2x;
undo/redo/save/reopen phases pass; RTL synthetic (`שלום` + a neighbour): neighbour shifts left,
right edge of the edited word unchanged; a shifted line that passes the measure gives the Q1
outcome (model raises `REFLOW_DOES_NOT_FIT` with the page bytes unchanged, the Controller offers
"enlarge" / "cancel", cancel mutates nothing).

**Slice 2: multi-line reflow.** Inserted lines, following lines, convergence, hard breaks,
line-end hyphens kept (Q4), justification, CJK, mixed styles, the floor outcome (Q1: `does_not_fit`
-> keep the text and offer, never a push-down). Acceptance: section 7.1 tests; corpus
`multicolumn.pdf` `pg0_b4_p0` `ipsum` -> `ipsums` and `ipsum` -> `ipsum-lorem`: pass = SUCCESS or
the Q1 not-fit outcome (zero mutation, typed text kept, offer shown), converged tail untouched
(glyph origins), zero-diff outside the band; a rejoined TeX word may print with its hyphen mid-line
(`adip-iscing`, D6) -- that is the disclosed Q4 consequence, not a failure; the number of redrawn
lines is RECORDED against the original-width prediction (2 and 18, section 2, re-measured in Slice
0 with hyphens kept), not asserted -- D9 measures in the draw font, where convergence is rarer.
Title `Two-Column` -> `Two-Colunm` one line, rest shifted right (Q3: a centred single-line
paragraph keeps its start and baseline and grows right, no re-centring); the right column and
everything above/below the paragraph zero-diff.

**Slice 3: preview ghosts, consent line count, docs.** `ReflowPreview`, the 「將重排 N 行」 line in
`_fallback_confirmation_message` (Q5), ARCHITECTURE / PITFALLS / FEATURES / TODOS, codegraph
re-index. Acceptance: a controller test
that the DTO reaches the view with the moved runs; `test_reflow_consent_names_the_line_count`
green; the UI phase matrix (section 7.3) complete.

**Slice 4 (deferred, own plan): Tier 2R.** Section 10.

## Test strategy

### 7.1 Red-first tests (each written and shown failing before its implementation)

`test_scripts/test_text_reflow.py` (pure, synthetic PDFs via `insert_text`, no Qt):
- `test_visual_lines_group_by_baseline_not_line_idx` (a Td-split line yields one visual line).
- `test_hard_break_is_inferred_when_the_next_word_would_have_fit`; `test_first_line_indent_starts_a_new_unit`;
  `test_a_line_ending_in_a_hyphen_is_never_a_hard_break` (D4, Q4).
- `test_detects_justified_vs_ragged_vs_centred`.
- `test_measure_falls_back_to_the_nearest_wall_for_the_widest_line_or_a_two_line_paragraph` (Q10): when
  the edited line is the widest, or the paragraph has two lines, the measure is the nearer of
  `_right_wall` and the left edge of the nearest non-member run in the band, not max `x1`; a
  three-line paragraph whose edited line is not the widest still uses max `x1` (contrast case).
- `test_centred_single_line_keeps_its_start_and_grows_right` (Q3): a centred one-line paragraph gets a
  plan whose line keeps its original start x and baseline, whose right edge moves right by exactly the
  growth, and which is not re-centred.
- `test_break_lines_keeps_latin_words_whole_and_breaks_at_spaces`; `test_break_at_a_typed_hyphen`;
  `test_line_end_hyphen_is_kept_on_rejoin` (Q4, replaces `test_soft_hyphen_rejoins_and_rebreaks`:
  `adip-` + `iscing` rejoin as ONE token `adip-iscing`, never `adipiscing`; mid-line it prints with
  the hyphen; where it must break again it breaks only after the hyphen, which stays at the line
  end; `Two-` + `Column` follows the same rule whatever the case of the continuation; no hyphen is
  inserted or dropped anywhere);
  `test_u2011_non_breaking_hyphen_is_never_a_break_point` (the reflow breaker breaks only after an
  existing U+002D / U+2010, the shipped D-HYPHEN-WRAP rule: a word joined by U+2011 wraps whole or
  overflows, and nothing is inserted);
  `test_cjk_breaks_between_characters_with_kinsoku`;
  `test_rtl_line_grows_left_from_a_fixed_right_edge`; `test_mixed_direction_line_refuses`.
- `test_convergence_stops_at_the_first_unchanged_line_and_baseline`; `test_no_convergence_rewrites_to_the_paragraph_end`.
- `test_inserted_line_continues_the_median_leading`;
  `test_a_tail_past_the_column_floor_reports_does_not_fit_and_keeps_the_typed_text` (Q1, replaces
  `test_refuses_when_the_tail_passes_the_column_floor`: the planner returns reason `does_not_fit`
  and no plan, touches no page object, and leaves the typed text it was given unchanged).
- `test_justified_line_distributes_slack_over_gaps_and_last_line_stays_ragged`.
- `test_mixed_fonts_keep_each_tokens_style_and_baseline`.
- Boundaries: empty new text (deletion: no reflow, today's path), a one-run paragraph, a one-line
  paragraph, the last line of the page, bad types.

`test_scripts/test_edit_text_helpers.py` (model path, `engine` legacy and tiered with
`allow_rebuild=True`): `test_reflow_shifts_the_rest_of_the_line_by_the_growth`,
`test_reflow_rewraps_the_following_lines_until_convergence`,
`test_reflow_never_touches_a_glyph_outside_the_paragraph` (glyph-level diff),
`test_reflow_keeps_a_same_line_table_cell_as_a_wall`, `test_reflow_replays_a_protected_watermark_in_place`,
`test_reflow_on_a_rotated_page_keeps_every_line_start`,
`test_reflow_undo_restores_the_page_and_redo_restores_the_after_snapshot`,
`test_reflow_survives_save_reopen`, and the dedicated tests for the owner answers:
- `test_shorter_replacement_does_not_reflow` (Q2): a shorter replacement leaves every other run's
  origin exactly where it was (the gap stays), `pending_chain` has no `legacy:reflow`, and the
  outcome equals today's path.
- `test_paragraph_mode_edit_uses_the_breaker` (Q6): with `target_mode="paragraph"` the first-line
  indent survives, unchanged leading lines keep their glyph origins (not redrawn), and the re-broken
  lines equal the breaker's `ReflowPlan`, not the one-box MuPDF re-wrap.
- `test_no_line_cap_on_a_long_rewrite_and_the_consent_discloses_the_count` (Q8): a fixture with free
  room below and a growth that never converges rewrites at least 20 lines (more than the 18 of the
  corpus probe) and commits; no cap constant exists; the consent callback receives N = the number of
  lines actually redrawn.
- `test_reflow_does_not_fit_raises_before_consent_with_zero_mutation` (Q1, replaces
  `test_reflow_refuses_with_zero_mutation_when_the_tail_does_not_fit`): a tail past the floor raises
  `TextEditRefused(REFLOW_DOES_NOT_FIT)` (not `TEXT_DOES_NOT_FIT`), the consent callback is never
  called, and the page bytes, `_page_glyphs`, the command stack and `pending_edits` are identical
  before and after; no `_push_down_overlapping_text` call.

`test_scripts/test_reflow_controller.py` (new; controller path, Qt offscreen, the twin of the
`test_s17_place_*` tests; the zh-TW sentences are built in the Controller, so these live here):
- `test_reflow_consent_names_the_line_count` (Q5): the real `_fallback_confirmation_message`, given
  the line count the model hands the consent callback, contains exactly 「將重排 N 行」 with
  N = re-broken original lines + inserted lines (and 「將重排 1 行」 for one line); a rebuild consent
  without a reflow does not contain 「將重排」.
- `test_reflow_does_not_fit_keeps_the_typed_text_and_offers_enlarge_or_cancel` (Q1): on
  `REFLOW_DOES_NOT_FIT` the Controller calls `confirm_enlarge_box` exactly once with the zh-TW
  sentence, shows no plain `show_error`, records no REJECTED result that would clear the editor
  (`_last_edit_result` stays None, so the View keeps the editor and the typed text), and does not
  ask the rebuild consent.
- `test_reflow_does_not_fit_cancel_is_zero_mutation` (Q1): after the 「取消」 answer the page bytes,
  the undo/redo stacks and tooltips, `pending_edits` and the dirty flag are unchanged, and no command
  was executed.
- `test_reflow_does_not_fit_enlarge_returns_to_the_kept_editor_without_mutation` (Q1): the
  「手動放大文字框」 answer mutates nothing either and leaves the typed text in the editor; a following
  Apply with a dragged `new_rect` takes the S17 path (D21), never the reflow branch.

### 7.2 Existing tests whose expectation flips (listed so nobody "fixes" them silently)

- `test_rebuild_wrap_at_the_neighbour_never_draws_over_the_same_block_line_below[legacy|tiered]`:
  `_same_block_pdf` puts `ab`, the red neighbour and the next line in ONE block = one paragraph
  (probe: all nine runs in `pg0_b0_p0`). Today asserts `TEXT_DOES_NOT_FIT`. In Slice 1 the edited
  line is the paragraph's widest line, so D5's fallback measure applies (`_right_wall`, about
  480 pt on this page): the 32 pt growth fits and the red run shifts right -- the outcome becomes
  SUCCESS with the second line untouched; the `_overprinted` invariant is kept. Slice 2
  flips it again: line 1 is a soft break (it ends at the measure), so `ef` wraps and `second line
  untouched` is RE-BROKEN (it is inside the band). New assertions: no overprint, every word of the
  block present, nothing outside the block changed; the "untouched second line" assertion is
  dropped and the test renamed.
- `test_rebuild_wrap_at_the_page_margin_never_draws_over_the_same_block_line_below` and
  `test_rebuild_wrap_of_a_whole_first_line_pushes_the_rest_of_the_paragraph`: under Slice 2 the
  long text wraps inside the paragraph (inserted lines) only if the floor allows; otherwise the Q1
  outcome (`REFLOW_DOES_NOT_FIT`, zero mutation, typed text kept, offer "enlarge" / "cancel"; never a
  push-down). Both already accept SUCCESS-or-refusal (for a reflowable edit the refusal code becomes
  `REFLOW_DOES_NOT_FIT`); add "tail untouched from the converged line" and "never calls
  `_push_down_overlapping_text`" guards.
- Flip in Slice 1 unless the fixture changes (D20): `test_rebuild_never_overprints_untouched_right_neighbour`,
  `test_rebuild_refuses_when_the_text_cannot_fit_before_the_neighbour`,
  `test_rebuild_never_overprints_a_neighbour_that_starts_inside_the_edited_extent` assert "the
  untouched neighbour moved" is false, but `NEXT` is a member of `ab`'s paragraph (probe), so Slice
  1 shifts it. Default per D20: keep the three tests on a provable CELL fixture (`ab` + 20 pt gap +
  `NEXT`, same font and size, one PyMuPDF line) where the wall semantics still hold, and add reflow
  twins on the member fixture asserting the shift, no overprint and the unchanged `Below line`.
- `test_multi_tab_plan.py::test_03_edit_in_a_undo_in_b_isolated` already edits a one-word page
  (F13-VF-4); unaffected.
- Separate-block cases stay as they are: `test_rebuild_wrap_still_pushes_a_separate_block_below`
  (push-down of a separate block is the old wrap path and is not reached by a reflowable edit;
  confirm with a guard that a reflow never calls `_push_down_overlapping_text`).

### 7.3 Real-corpus fidelity acceptance (per `.agents/skills/pdf-text-fidelity/references/acceptance.md`)

Per case a phase matrix (select/input, preview, Apply with the actual `CommitOutcome`, Undo, Redo,
Save/Reopen), each pass / fail / not_run / blocked, with source sha256, page index, run id,
old -> new text, code revision + dirty diff id. Mask = the reflow band (`touched_lines` only: the
edited line through the last re-broken line, x = column; the converged line is outside it), never
wider. Checks: 6x crop of the band before/after, side by side;
2x whole page diff = 0 pixels outside the mask, MuPDF and Poppler each against itself
(`PDF_EDITOR_PDFTOPPM`); untouched lines inside the mask (converged tail) compared by glyph origin.
Cases: (a) `google-doc-document.pdf` p1 `better` -> `better-than-ever` (Slice 1), expected one
line, `Readability counts.` etc. zero-diff; (b) `multicolumn.pdf` p1 `ipsum` -> `ipsums` (Slice 2,
converges within 2 lines before Q4; re-measured with hyphens kept, and a mid-line `adip-iscing` is
the disclosed Q4 consequence, not a defect) and `ipsum` -> `ipsum-lorem` (long tail or the Q1
not-fit outcome), the right
column zero-diff; (c) `multicolumn.pdf` title `Two-Column` -> `Two-Colunm` one line; (d) a local
CJK paragraph case and an RTL case chosen with the owner (the 14 HVAC/ECC cases are single-line
drawing labels and do not exercise reflow; they must still pass unchanged as regression).
Refusals are negative passes, never counted as edits; the Q1 offer is recorded the same way, with
its two answers as separate rows ("enlarge" and "cancel" both checked for a zero page diff and the
typed text still in the editor).

## Dead ends and risks

- MuPDF `insert_htmlbox` cannot justify a single line nor honour `word-spacing` (measured): per-word
  placement is the only route; cost = one `insert_text` per Latin-1 token, one htmlbox + placement
  probe per other token (mitigated by D11 merging and `font_compaction_scope`).
- Substitute-font widths differ from the original, so convergence is rarer than the original-width
  simulation suggests and a whole-paragraph rewrite in the substitute font is visually loud
  (T16-5). This is why Tier 2R exists; Q8 (owner-confirmed): no cap on the redrawn line count, the
  consent discloses it.
- Rejected by the owner (Q1): pushing the next block down to make room, and a silent refusal that
  drops the typed text. The chosen outcome keeps the text and offers "enlarge the box manually" /
  "cancel".
- Hard vs soft BREAK cannot be proven from a PDF; D4 is a heuristic and will misfire on poetry-like
  text whose lines happen to end near the measure. Mis-inference never overprints (guards stay), it
  only changes which words share a line. Hyphens need no inference since Q4: every line-end hyphen is
  kept (D6). The price is visible and accepted by the owner over silently dropping a character: a
  hyphen that exists only because TeX hyphenated the word at a line end stays printed when the
  rejoined word no longer sits at a line end (`adip-iscing` mid-line), a rejoined word may break
  again only after its hyphen, and the redrawn line counts may be higher than the pre-Q4 simulation
  suggested (to be measured in Slice 0).
- A paragraph the index merged wrongly (two cells rule (a2) left joined, label/value pairs below
  3.0x) would reflow across the join; D15's wall only covers cells rule (a) cut. Mitigation: refuse
  reflow when a line's inter-run gap exceeds `_SAME_BASELINE_GAP_RATIO` at the shift point.
- Replaying a protected neighbour with an `offset` changes `_protected_span_drawn_in_place`'s
  expectation; both sides must use `_start_point`, never the first drawn glyph (F15-VM2-RTL).
- Reopen anchor migration after a wrap (D17) touches `_run_anchor_score`, which already has an open
  defect (TODOS F14-ANCHOR-STALE); do not widen it, add a test per Slice.
- `pdf_text_edit.py` is being edited by another agent on this working tree; this plan cites
  functions, not line numbers.

## Owner answers (2026-10-12)

- Q1 Growth past the free space below: neither silent refusal nor push-down. Keep the edited text
  (do not discard it) and ask the user either to widen/enlarge the text box manually or to cancel
  the edit. This replaces the "refuse" default in Slice 1.
- Q2 Shorter replacement does not reflow (default kept).
- Q3 Centred single-line paragraph keeps its start and baseline, grows right (default kept).
- Q4 OVERRIDDEN: a line-end hyphen is always kept as a character; it is never dropped on rejoin.
  The breaker may still break after an existing U+002D/U+2010 (D-HYPHEN-WRAP), never at U+2011.
- Q5 Reflow reuses the rebuild consent with 「將重排 N 行」 (default kept).
- Q6 Paragraph-mode edits use the breaker too (default kept).
- Q7 Tier 2R after the part-5 defects (default kept).
- Q8 No line cap; the consent discloses the count (default kept).
- Q9 Member runs on the edited line move with the edit; the F13-VF-4 wall applies only to
  non-member cells (default kept).
- Q10 Widest line / at most two lines: the measure is the nearer of `_right_wall` and the nearest
  non-member run in the band (default kept).

## Deferred: Tier 2R, in-stream reflow with the original font (own plan after Slices 0-3)

Goal: the same `ReflowPlan`, applied as a multi-replacement `PatchSet` (`PatchSet.replacements` is
already a tuple) that rewrites the paragraph's show operators in the original font resource
(encoding through the Tier 1 encoders and the T16-4X glyph gate) instead of redrawing in a
substitute font: for `Tj`-per-word + `Td` paragraphs (Google Docs / Word) by patching string operands
and `Td` operands; for `TJ`-per-line paragraphs (TeX) by rebuilding the array items and kerns. Needs:
paragraph -> shows binding (extend `source_run.group_page_runs` from one line to N lines), a
`patch.py` builder, a verifier that proves every moved glyph landed on its planned origin and
nothing outside the band changed (texttrace + raster), and the Slice 0 census to say which shapes
are worth it. Not designed here.

## Log

- 2026-10-12: plan written from code reading and read-only probes (section 2). No code changed.
- 2026-10-12: owner answered Q1-Q10 (see "Owner answers"). Q1 and Q4 differ from the defaults:
  D4/D6 soft-hyphen handling and the Slice 1 "does not fit" refusal must be revised before Slice 1
  is built (keep the edited text, offer "enlarge the box" or "cancel"; never drop a hyphen).
- 2026-10-12: owner: build Slices 0-3 only after the adversarial review loop converges.
- 2026-10-13: plan revised to agree with the owner answers (no code changed). Q1: Goal, D2, D8, 4.2-4.4,
  4.6, Slice 1/2 and 7.2/7.3 now keep the typed text and offer "enlarge the box manually" / "cancel"
  (new refusal code `REFLOW_DOES_NOT_FIT`, `_offer_enlarge_box`, `confirm_enlarge_box`; proposed
  labels 「手動放大文字框」 / 「取消」) instead of a zero-mutation refusal, shrink or push-down; replaced
  `test_refuses_when_the_tail_passes_the_column_floor` and
  `test_reflow_refuses_with_zero_mutation_when_the_tail_does_not_fit` with
  `test_a_tail_past_the_column_floor_reports_does_not_fit_and_keeps_the_typed_text`,
  `test_reflow_does_not_fit_raises_before_consent_with_zero_mutation` and the controller tests
  `test_reflow_does_not_fit_keeps_the_typed_text_and_offers_enlarge_or_cancel`,
  `test_reflow_does_not_fit_cancel_is_zero_mutation`,
  `test_reflow_does_not_fit_enlarge_returns_to_the_kept_editor_without_mutation`. Q4: D4, D6, Measured
  facts and Dead ends rewritten (a line-end hyphen is always kept, `adip-` + `iscing` -> `adip-iscing`,
  break only after an existing U+002D / U+2010, never U+2011; the 2 / 18-line figures predate Q4 and are
  re-measured in Slice 0); `test_soft_hyphen_rejoins_and_rebreaks` ->
  `test_line_end_hyphen_is_kept_on_rejoin`, plus `test_u2011_non_breaking_hyphen_is_never_a_break_point`
  and `test_a_line_ending_in_a_hyphen_is_never_a_hard_break`. New dedicated tests for the confirmed
  defaults: `test_shorter_replacement_does_not_reflow` (Q2),
  `test_centred_single_line_keeps_its_start_and_grows_right` (Q3), `test_reflow_consent_names_the_line_count`
  now asserts 「將重排 N 行」 and moved to `test_reflow_controller.py` (Q5),
  `test_paragraph_mode_edit_uses_the_breaker` (Q6),
  `test_no_line_cap_on_a_long_rewrite_and_the_consent_discloses_the_count` (Q8),
  `test_measure_falls_back_to_the_nearest_wall_for_the_widest_line_or_a_two_line_paragraph` (Q10).
  D21 added: dragged edits never reflow and follow S17-DRAG-GUARD and the 2026-10-13 drag offer
  ("move to nearest free spot / place anyway / cancel"). Also corrected a stale name: no
  `_ask_rebuild_consent` exists in code; the consent text is `_fallback_confirmation_message`.
- 2026-10-13: owner confirmed Q1 cancel keeps the editor open with the typed text (nothing applied; Esc leaves).
