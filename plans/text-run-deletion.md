# Plan: text-run deletion (to_Update 「要可以完全刪除文字框」)

<!-- Paths are repo-relative on purpose (device-guard). Status: PLAN ONLY, nothing implemented. Revised 2026-11-05 after adversarial review. -->

## Current state / next step (≤40 lines)

- **Request:** the owner wants to fully delete existing text (`docs/to_Update.md:34`). It is also tracked as an open TODO (`TODOS.md:1626`).
- **App-created boxes already delete.** Use "Delete Object" (`view/pdf_view.py:6264-6270`). Emptying one also drops its marker (`model/pdf_object_ops.py:1852`).
- **Native text cannot be deleted by the engine today.** `model/text_commit/plan.py:1880-1883` refuses `""` with `EMPTY_REPLACEMENT`. The owner decided on 2026-09-30 that emptying is rebuild-only (`test_text_commit_no_silent_legacy.py:351-356`).
- **The probe's "silent" refusal is unexplained.** The production `PDFView` has `_show_toast` (`pdf_view.py:2771`), so a REJECTED result already shows a warning toast. The no-toast `logger.info` branch (`pdf_controller.py:3356-3361`) only runs on test doubles. Step 0 (U0) diagnoses this in the real view.
- **The primitive exists and is measured but unused.** `patch.build_advance_preserving_erase` (`patch.py:254-294`) emits a glyph-free `[N] TJ` with `N = -1000·d/Tfs` (`kern_for_displacement`, `:297-339`). Task 10 rated it GO (`TODOS.md:1723`).
- **Design.** Add an erase plan kind reported as TIER1 with a new `SPLICE_KIND_ERASE_OPERATOR`. It gets its own positive-erasure verifier, and a single `is_erase(prepared)` predicate is used at every `is_tier1` site. It reuses the existing token, preview, commit and reversal-PatchSet undo. v1 erases exactly one proven show; v2 handles N shows.

**Owner decisions needed before coding:**
- **D1.** Supersede the 2026-09-30 "emptying is rebuild-only" decision for single-show targets. Recommended: **yes**.
  - **D1a. Cross-page move source leg** (`pdf_controller.py:3941-3960` calls `edit_text("", allow_rebuild=True, moving_off_page=True)`). With D1 in place, an admissible source is erased losslessly instead of redacted and rebuilt. The move consent still fires every time, because it is asked unconditionally before the leg (`:3895-3900`). `_is_notifiable_degrade` (`:3978`) stops firing for that leg. Recommended: **accept** (strictly less destructive), and rewrite `TODOS.md:1823-1827`, whose stated reason is stale.
- **D2. Triggers.**
  - Primary: empty the editor and press Apply.
  - Secondary: a context-menu 「刪除文字」 that commits directly, with no modal (undoable). Recommended: **yes**.
  - **D2a.** Every in-place commit with a verified token (click-away, mode or session change, Ctrl+S, R4-4 click on another run) commits a deletion, not only Apply (`view/text_editing.py:3307-3316`, `pdf_view.py:5155-5169`). Recommended: **accept**, consistent with edits. The deletion toast fires on every path and names Ctrl+Z. The alternative is an explicit-Apply-only flag on erase tokens.
- **D3.** Latch `secure_save_required` on deletion? Recommended: **no**, consistent with text edits. Confidentiality stays with redaction (Q3).

**Next step:** owner answers D1, D1a, D2, D2a and D3. Then Step 0 (U0, U0b evidence plus C0′ red), then Step 1.

---

## 1. Goal and semantics

Delete a native text show so that its glyphs disappear and every other byte and pixel stays put. No reflow (「不跳」): a visible gap is intended.

| UI target | Engine target | v1 |
|---|---|---|
| Proven run-mode show group (`pdf_text_edit.py:4562-4596`, `source_run.py:13-50`) | one `ShowOp` | erase the whole op |
| Whole word that is its own `Tj` (`_tier0_target_from_resolve`, `:4441-4559`) | one `ShowOp` | erase it; a gap remains |
| Full line made of one show | one `ShowOp` | erase |
| Line or paragraph made of several shows | N ops | refuse `multi_span_target`; the mapped sentence points at 「改用重建文字…」 (v2: N-erase) |
| App FreeText / textbox | marker object | unchanged (`delete_objects_atomic`, `pdf_object_ops.py:2506`) |
| Substring of a show | n/a | a replacement edit, not a deletion |

**Expected reach (unverified; Step 6 measures it).** Roughly the HVAC/ECC shapes (single hex `Tj`, `docs/experiments/2026-09-21-hvac-font-edits.md:43`). Structural-MC wrappers refuse (`marked_content.py:418-422`). The T16-4X census says this blocks most Office output.

**Invariants (each is a test):**

- **Pen position.** Let `d` be the whole consumed advance in unscaled text space: `d = Σ w(code)·Tfs/1000 + Tc·n_codes + Tw·n_0x20 − Σ k_i·Tfs/1000`.
  - `n_codes` counts codes, not decoded chars. `n_0x20` counts single-byte `0x20` bytes in `show.decoded_bytes`, and is 0 for Identity-H 2-byte codes. Do **not** reuse `_advance` (`plan.py:305`, which uses `len(text)` and `text.count(" ")`).
  - Th cancels (`patch.py:303-306`). Tc and Tw are not applied to kern numbers (`:263-268`).
  - Folding the trailing kern is mandatory. `tier0_show_gate` admits `[(x) k] TJ` (`plan.py:1273-1275`) (PITFALLS_INDEX:397 class).
- **Horizontal writing only.** Only Identity-H is admitted (`cid_fonts.py:1143`), and vertical writing is out of the binder's scope (`source_run.py:275`). Pinned by E6.
- **Byte scope.** Only `op_start:op_end` changes. Tf/Tm/Tc/Tw/Tz/Ts/Tr, colour, BT/ET, BDC/EMC and q/Q stay byte-identical. An empty BT…ET left behind is harmless.
- **Neighbours.** Char origins (not just span origins) and outside-halo pixels (ε = 0) stay unchanged.
- **Whitespace.** The engine treats only exact `""` as deletion. The View normalises a whitespace-only editor to `""` before both the preview and the commit.

## 2. Engine (Model only, Qt-free)

**Modules:** `model/text_commit/{dto,plan,patch,verify,engine,preview}.py`, `model/edit_commands.py`, `view/text_edit_reasons.py`.

### 2.1 DTO
- Add `SPLICE_KIND_ERASE_OPERATOR = "erase_operator"`. It is folded into the token. The verifier refuses unknown kinds (`dto.py:205-211`).
- Add RejectReasons `ERASE_TARGET_STILL_PRESENT` and `ERASE_TARGET_NOT_VISIBLE`. Each gets a sentence, as enforced by `test_text_commit_rebuild_action.py:186-192`.
- Add a `PageState` field `erase_zone_glyphs: int` and an erase-zone pixel accessor. They are filled only for the erase kind, in **both** `capture_page_state` and `_page_state_from_baseline` (`verify.py:345-374`), because `growth_zone_glyphs` exists only under `has_ink_growth` (`:355-362`). The pre-pixels are already whole-page (`pixmap_samples = bytes(pixmap.samples)`, `:231`, `:429`), so no extra raster is needed.
- `HIGH_FIDELITY_TIERS` is unchanged. The TIER1 report gives reversal-PatchSet capture (`edit_commands.py:454,516`).

### 2.2 Planner (`plan.py`)
- **`prepare_plan` (`:2666-2710`).** When `replacement_text == ""` and `max_tier >= 1`, call `_classify_common(..., erase=True)` and then `_build_erase`. `prepare_tier0_plan` and `max_tier == 0` keep `EMPTY_REPLACEMENT` (pin: `test_text_commit_tier0.py:166-198`).
- **`_classify_common(erase=True)`.** Same ladder:
  - skip the EMPTY gate;
  - STYLE/GEOMETRY overrides still refuse;
  - widget/signature, inline annots, page frame, bind, `'`/`"` (`:1970-1984`), `SHARED_CONTENT_STREAM`;
  - `tier0_show_gate` is unchanged. It includes rise (`:1726-1733`), the render-mode ladder, Tz, MC wrappers (ActualText → `MC_WRAPPER_NOT_PURE_LAYER`, `marked_content.py:248,418-422`), Type3 and Type0 scope;
  - codec: keep the source-reproduction proof (`:2036-2044`, `:2077-2082`), the source glyph gate and `uncovered_codes`. Skip every replacement-side gate;
  - keep the reflected-TRM refusal;
  - call `duplicate_source_painter_detail` with `replacement_cids=()`. The review confirmed `predict_glyphs` returns `[]` (`glyph_boxes.py:363-389`), so the twin is compared against the source ink.
- **`_build_erase`:**
  - fence `render_mode != 0`;
  - fold kerns from `tj_item_spans` (`TjSpan.kern`, `glyph_boxes.py:205-209`); a `None` result gives `TJ_ITEM_RELEX_FAILED`;
  - compute `d` via the new `patch.consumed_show_advance(stream, show, capability)`, using the code-level counts above, then `build_advance_preserving_erase`;
  - turn a `ValueError` into `UNSUPPORTED_TEXT_STATE` (as at `:2567-2576`);
  - `PreparedEdit` fields:
    - `tier=TIER1`, `splice_kind=ERASE_OPERATOR`;
    - `replacement_text=""`, `replacement_advance=0`;
    - `source_advance=d`, `kern_adjustment=N`;
    - `font_resource`, `font_xref`, `binding`, `original_text`, `page_fingerprint` and `target_bbox_page` (all as the Tier 1 build sets them);
    - `background_bbox_page = target_bbox_page`, `has_ink_growth=False`;
    - token from `_content_token(..., splice_kind=ERASE_OPERATOR)`.

### 2.3 Engine dispatch chokepoint (`engine.py`, `preview.py`)
- `is_tier1` drives more than the verifier choice: `engine.py:231-244, 271, 301-326, 347, 369-371, 387, 443, 454` and `preview.py:314, 366`.
- Add `verifier_for(prepared)` and use it at `:271`, `:387` and `preview.py:366`.
- Leave font-outcome sites `:231` / `:301` / `preview.py:314` running for the erase. `build_tier1_font_outcome` proves resource reuse (`patch.py:397-425`), the erase keeps the Tf resource, and `CommitOutcome` needs a `FontOutcome` (`:466`). That avoids a fourth kind-dispatch.
- **Chains.** `_tier1_chain` (`:77-81`) and the success chain (`:449-458`) hard-code "Tier 1 is reached only via ADVANCE_MISMATCH". For the erase, use:
  - `("tier0:rejected:empty_replacement", "tier1:erase:committed")` on success;
  - `("tier0:empty_replacement", "tier1:<reason>")` on failure.
  - Keep the last entry in `tier1:<RejectReason>` form, because `pdf_text_edit.py:4824-4825` splits it for the GUI reason.
  - Update the comments at `:449-452`, `:77-80` and `dto.py:286`. Grep `scripts/evidence_rederive.py` for `decision_chain` consumers.

### 2.4 Verifier `verify_erase_commit`
`_verify_patch_postconditions` (`verify.py:632`) runs with the replacement-text check (vacuous for `""`) replaced by these checks:
- **(a) Census.** Count non-space rawdict chars whose origin lies in the target box, routed through `_visual_bbox_to_dict_space` (`verify.py:324`). The post count must equal the pre count minus the target's non-space glyph count, and no char may sit at the target's origin or advance positions.
- **(b) Pixels.** The target-region raster must differ from pre. Identical gives `ERASE_TARGET_NOT_VISIBLE` (fail closed).
- **(c) Char-level neighbour origins (mandatory).** Every non-whitespace char outside the target box keeps its origin to within 0.01 pt. Span-level V0c (`:318-329`, ±1 pt exclusion, 0.1 rounding) is vacuous for a same-span successor.
- **(d) V0d.** Outside-halo identity (96 dpi, 2 pt, `:62-63`).
- **(e) `_target_operator_failure` erase arm** (beside `:605-611`). The payload at `op_start` must lex as exactly `[ NUMBER ] TJ`.

### 2.5 Refusals
Each refusal is zero-mutation, has a mapped sentence, and none falls through to legacy silently.
- **Font and operator:** Type3, `'`/`"`, Identity-V.
- **Page and structure:** shared stream, Form XObject, widget or signed page (plus `pdf_model.py:5270-5295`), inline annots.
- **Text state:** Tr ≠ 0, rise, reflected or sheared TRM, non-pure MC (including ActualText).
- **TJ shape:** multi-item TJ, leading kern.
- **Font proof:** unprovable widths, twin painter.
- **Targeting:** unresolved, reconstruction or multi-show target.
- **Verification:** `verification_failed` / `erase_target_*`.
- **Wording:** the reasons an emptied editor most often hits (`multi_span_target`, `mc_*`) say 「可改用重建文字…」 in the deletion context.

### 2.6 Model glue
- `_attempt_tiered_commit` (`pdf_text_edit.py:4696`) already passes `""`; no change expected, confirmed by test.
- `_sync_textbox_objects` with `""`: page text under an app box gives a no-op (`pdf_object_ops.py:1880-1889`). Pinned in E12.
- `EditTextCommand.description` (`edit_commands.py:316-322`): when `new_text == ""`, return `刪除文字「<original[:20]>」（頁面 N）`.

## 3. Controller and View
- **Controller.** No `_show_notice_feedback` change: a modal there would break the never-a-modal contract (`:3328`, `:3776-3777`) and block toast-less Qt tests on PENDING/STALE. On SUCCESS with `new_text == ""`, show the toast 「已刪除文字（可按 Ctrl+Z 復原）」 on every commit path (D2a). The cross-page move follows D1a.
- **Primary trigger.**
  - Normalise whitespace to `""` before `_emit` and the finalize request.
  - Show the Apply label 「刪除」 when the editor is empty.
  - The preview path emits for any text (`text_editing.py:2825-2854`), and `apply_permitted()` (`:2991`) unlocks.
- **Paint.**
  - Plan mode shows the frozen original with the badge while the preview is pending, by design (`:1834-1847`). After the erase preview lands it shows the preview frame, which has no source glyphs.
  - Non-plan mode with empty text has two fallthroughs:
    - a stale previous-keystroke `_preview_image` is painted, because the fail-safe requires `_text_is_nonempty` (`:1694-1711`);
    - otherwise the frozen first frame is painted (`:1719-1720`).
  - Fix: in non-plan mode, empty text paints the background mask only until the erase preview lands.
- **Context menu.** Add 「刪除文字」 when `text_hit` is set, in **both** `browse` (beside "Edit Text", `pdf_view.py:6274-6281`) and a new `edit_text` branch.
  - If an editor is open, apply the R4-4 rule first (`:5155-5169`); if the editor survives, show nothing.
  - Build the same target fields as `_start_text_edit_from_hit`.
  - Emit `EditTextRequest(new_text="", requires_preview_token=False, session_id=<active>)`.
  - When the point also hits an app object, show both items. "Delete Object" acts on the object; 「刪除文字」 acts on the page text under it.
- **Delete key.** No change (`pdf_view.py:3223`).

## 4. Tests (red-light first)

Engine tests go in `test_scripts/test_text_commit_erase.py`. Fixtures are raw streams. The oracles are helv `/Widths` and hand-computed kerns, never the implementation's formula.

**Step 0:**
- **C0′.** A QTest on the real `PDFView`. An inadmissible empty edit must show the warning-toast `QLabel` text; record it.
- **U0.** Real app (`main.run(..., start_event_loop=False)`): select all, Delete, wait for the preview. Record the sentence, the Apply state, the paint, and whether a toast appears. If it is silent, diagnose in the View.
- **U0b.** The consented rebuild with `""`: record the residue.

| ID | Case | Assert |
|---|---|---|
| E1 | single `Tj` line plus a 2nd line | kind is `erase_operator`; op bytes equal `[N] TJ` from the oracle; text gone; 2nd-line char origins equal |
| E2 | `(Delete) Tj ( keep) Tj`, Tc∈{0,1.5}×Tw∈{0,3}×Tz∈{100,80}; plus a `/Differences` font where code 32 ≠ space and a ToUnicode code→"fi" | "keep" origins within 0.01 pt; 2x pixels outside the halo identical; fixture guard: a naive `[]TJ` moves "keep" > 0.1 pt |
| E3 | target and successor in one MuPDF span | char-level (c) passes; span-level V0c alone recorded |
| E4 | `[(abc)]TJ`; `[(abc) -250]TJ`; Identity-H hex; quarter-turn Tm with Tz 79.98; uniform scale; `/Rotate 90`; `/Rotate 270` + offset CropBox | success; successor unmoved; census correct on rotated pages |
| E5 | Tier 1 edit → `[<..> K]TJ`, then delete | success; successor unmoved |
| E6 | Type3, `'`, `"`, shared stream, Form XObject, widget, inline annots, Tr 2/3/7, rise, reflected, multi-item TJ, leading kern, unprovable width, `/ActualText` MC, Identity-V | reason code, detail substring, byte-identical streams |
| E7 | `max_tier=0` | `EMPTY_REPLACEMENT` |
| E8 | op left intact; text under an opaque rect; payload `[(x) N]TJ` | `ERASE_TARGET_STILL_PRESENT`; `_NOT_VISIBLE`; the operator arm refuses |
| E8d | the planner is patched to emit a wrong N: drop Tc·n, drop the trailing kern, +0.1 pt, +0.3 pt | `verify_erase_commit` refuses each one on **both** the commit and preview paths |
| E9 | fill+stroke twin; same-text twin | `DUPLICATE_SOURCE_PAINTER` |
| E10 | `PlanPreviewRenderer("")` → token → commit; mutate the page then commit | success; `PREVIEW_STALE` |
| E11 | undo/redo via `EditTextCommand`; redo after an unrelated stream change | byte-identical restore; `STALE_PLAN` with zero mutation; description reads 刪除文字「…」 |
| E12 | incremental and `garbage=1` save, reopen; Poppler before/after; text under an app box | text absent; origins equal; markers unchanged |
| E13 | delete a word, then Tier 0/1 edit its successor; delete two adjacent words in sequence; delete, undo, edit | each succeeds; neighbours unmoved |
| E14 | chains | success chain is `tier0:rejected:empty_replacement → tier1:erase:committed`; a failure's last entry parses to its reason |

**Controller/View:**
- C1: a success shows the delete toast on Apply, click-away and Ctrl+S.
- C2: a refusal shows the mapped sentence on the real view.
- C3: a cross-page move with an admissible source. The consent is asked once, the source tier is TIER1 erase, there is no degrade notice, and undo restores.
- U1: empty, preview, Apply (label 「刪除」), Ctrl+Z, Ctrl+Y, Save, Reopen; the outcome and page state at each phase.
- U1b: empty, verified token, click another run (R4-4); the D2a behaviour.
- U2: no source glyphs after the erase preview lands. A non-plan stale previous-keystroke image is not painted for empty text. The pending state shows the frozen original with the badge (plan mode).
- U3: the context menu in browse and edit_text (an open editor plus R4-4) commits; it is undoable; `session_id` is stamped.
- U4: whitespace-only becomes `""`.

**Deliberate flips** (each named in the commit message as superseding 2026-09-30):
- `test_text_commit_no_silent_legacy.py:336`: move to a multi-show fixture and add a positive twin.
- `test_no_jump_editor_geometry.py:1013,1218`: re-check the empty-refused assumption.
- The cross-page move source tier (C3).
- `test_tier0_target_resolution.py:1238` and `test_text_commit_tier0.py:170` should stay green.

**Real corpus.**
- Driver: extend `test_text_commit_ui_real_corpus.py` with a delete leg for 14 cases (HVAC 10, ECC 4).
- Supervisor: run under `scripts/verify_supervise.py --stall 120 --ceiling 900`.
- Matrix per case: select, preview, Apply, Undo, Redo, Save/Reopen, each marked pass / fail / not_run / blocked.
- Measures:
  - 6x target crop blank;
  - 2x non-target diff 0;
  - neighbour char origins equal;
  - MuPDF and Poppler each compared with itself;
  - side-by-side crops inspected.
- Twin case: the `Buffer Tank` twin pair, where deleting one leaves the other byte- and pixel-identical.
- Record `source_sha256`, `show_seq` and the revision plus the dirty-diff id.

## 5. Steps
0. C0′, U0, U0b evidence in the log.
1. dto (kind, reasons, PageState fields), planner, `consumed_show_advance`, **`verify_erase_commit` + `verifier_for` + chains**, with E1/E2/E4/E5/E6/E7/E8/E8d/E14 red then green. The verifier must land here: `verify.py:605-611` refuses non-whole-operator kinds.
2. Preview path (`preview.py:366`), E3/E9/E10/E13.
3. Undo label, undo/redo/save, E11/E12.
4. Controller: delete toast on all paths, move leg (D1a), C1–C3.
5. View: normalisation, Apply label, paint fix, context menu, U1–U4.
6. Real-corpus 14-case matrix.
7. Done gates:
   - `ruff check .`, mypy `model/ utils/`, `scripts/run_suite.py`;
   - ARCHITECTURE (splice kind, `verifier_for`, chain shape);
   - PITFALLS (vacuous `"" in text` V0c; span-level V0c vacuous for same-span successors; whole-op erase must fold trailing kerns; Tw/Tc counted by code, not decoded char) plus an index regen;
   - TODOS: close `:1626` / to_Update:34 for single-show targets, rewrite `:1823-1827`, open Q7 and R1.

## 6. Open questions (recommended answers)
- **Q1/D1:** yes, for single-show targets. Multi-show targets keep the consented rebuild until v2.
- **Q2/D2, D2a:** yes; undoable, and the toast names Ctrl+Z.
- **Q3/D3:** no latch. An incremental save leaves the old stream in the prefix (PITFALLS:1484-1492, unverified by this revision), so the toast must not claim secure removal. Redaction covers confidentiality.
- **Q4:** the View normalises whitespace; the engine contract is exact `""`.
- **Q5:** refuse occluded or invisible targets (`ERASE_TARGET_NOT_VISIBLE`). Tr 3/OCR text is S7.
- **Q6:** refuse reflected text and Tr 2 in v1; revisit with a pen-aware halo in v1.1.
- **Q7 (v2):** one `PreparedEdit` with N `StreamReplacement`s (`patch.py:77-84`), multi-range V0a, binder proof of the member→show set, and twin erase. Needs a separate approval.
- **R1:** highlight/underline annotations over deleted text remain (V0b). Recorded in TODOS.
- **R2:** the mid-line gap is intended; no toast note.

## 7. Decisions / dead ends
- **Rejected: redaction-based delete.** It is geometric, destroys overlapping ink (PITFALLS_INDEX:177, 535) and re-serialises the stream.
- **Rejected: a new `CommitTier`.** It ripples through IntEnum consumers. The erase is TIER1 plus `splice_kind`, and the chains are kind-aware.
- **Rejected: `[() K] TJ` via `build_kern_compensated_transplant`.** The glyph-free `[N] TJ` is the measured Task 10 primitive.
- **Rejected: the `_show_notice_feedback` → `show_error` fallback** (review #3). Production already toasts. A modal would violate `:3776-3777` and hang toast-less Qt tests.
- **Rejected: skipping `build_tier1_font_outcome` for the erase** (review #16). It runs and reports `SOURCE_RESOURCE_REUSED`.

## Running log
- 2026-11-05: plan drafted (analysis only).
- 2026-11-05: revised after the adversarial review, with each point checked against the code.
  - **Accepted:**
    - #1: the chains are hard-coded (`engine.py:77-81, 449-458`); 11 `is_tier1` sites.
    - #3: `pdf_view.py:2771`, `message_boxes.py:12-14`.
    - #4: `verify.py:318-329`, so char-level (c) is now mandatory and E8d was added.
    - #5 → D2a.
    - #6 → E13.
    - #7 → E4 rotate cases and a census via `_visual_bbox_to_dict_space`.
    - #8: the citation was `plan.py:1866`, a docstring; corrected to `test_text_commit_tier0.py:166-198`.
    - #10: `plan.py:305`; extended to Tc counting codes.
    - #11: the verifier moves to Step 1.
    - #12: `text_editing.py:1694-1720, 1834-1847`.
    - #13: `pdf_view.py:6274`; session id (`pdf_controller.py:3786`).
    - #14: `edit_commands.py:316-322`.
    - #15: `cid_fonts.py:1143`.
    - #16: `patch.py:397-425`.
    - #17: `verify.py:355-372`.
    - #18: reach is stated, marked unverified.
  - **Rejected #9.** `TjSpan` carries `kern: float | None` (`glyph_boxes.py:205-209`), and `tj_items` and `tj_item_spans` share the one `_tj_operand_spans` relex with the count and `decoded_bytes` checks (`:212-260`). No cross-proof is needed.
  - **Partly rejected #2.** The behaviour change is real: the source leg erases, and `_is_notifiable_degrade` stops firing. The claimed consequence is wrong: the move consent is asked unconditionally by the controller before the leg (`pdf_controller.py:3895-3900`), so every move still prompts. It becomes D1a.
  - **Review's unverified items, now checked:**
    - rise is refused in `tier0_show_gate` (`plan.py:1726-1733`);
    - ActualText becomes `MC_WRAPPER_NOT_PURE_LAYER` (`marked_content.py:248, 418-422`);
    - pre-state pixels are whole-page (`verify.py:231, 429`), so (b) needs no new raster.
  - Still unverified: `PITFALLS.md:1484-1492` and the Task 10 GO note at `TODOS.md:1723` (cited from the first draft, not re-read).
