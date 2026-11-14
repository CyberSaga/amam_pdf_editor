# Review round 2 of `paragraph-grouping-reflow.md` revision 2 (2026-11-14): NOT CONVERGED

Record of both independent reviews, condensed, so revision 3 can be written without the transcripts.
R = deep-reasoner (Opus), X = Codex `gpt-6.1-sol`. Evidence lines are the reviewers' citations; the ones
marked (checked) were re-read by the main model. Nothing here is implemented.

## Rows of section 10 both reviewers accept as resolved

R2/X15 token dispatch (X only; R: partly), X5 structure consolidation, X6/R14 operator replacement as
INPUT admission, R7/X12 merged-paragraph consumers (A.5), R9/X7/X8 floor/attachments/rotation,
R10/R11/X10 donor proof and discovery, X13 convergence baseline, R16.

## Open findings, grouped by the plan change they need

### 1. Emission unit and re-edit (blocker; R1, X4, R14-minor, X5-new)
- C.5 writes several `Tm`/`TJ` (and `Tf` switches for donors) into one show's range; each `TJ` is its own
  `ShowOp` (`replay.py:538-586`), so after any wrap or donor switch the first is no longer "last show of
  its `BT`" and B refuses the paragraph on the next edit and for E after an edit (section 7 acceptance
  runs exactly that order). "Atoms never change show" cannot be a physical-show invariant.
- Emitted `1 0 0 1 x y Tm` drops a scaled `Tm`/CTM that B admits (`replay.py:107-123, 566`).
- Change: admission and splice unit = the whole `BT … ET` body of a `q` scope that holds only
  `Tc`/`Tf`/`Tm`/`Tj`/`TJ` (+ `Tw 0`, `Tz 100`) and no show after `ET`; rewrite the body as a whole
  (still inside `q..Q` and `BDC..EMC`). v1: identity linear `Tm` and identity CTM only. Red tests: edit,
  re-open, edit again; line pitch after a Tier 2R edit; edit -> edit -> undo -> redo with wrap and donor.

### 2. Donor transaction (blocker for donor edits; X1, X2, R2)
- `page_fingerprint` hashes the font table and font objects (`inspect.py:799-810`); `apply_patchset`
  gates on it (`patch.py:157-159`); `build_reversal_patchset` keeps stream replacements only
  (`patch.py:193-249`). Adding the donor before the stream patch invalidates the patch's pre-fingerprint;
  the inverse order leaves an intermediate state. LIFO alone is not a protocol.
- `EditTextCommand` builds its reversal by diffing one stream after `edit_text` returns
  (`edit_commands.py:452-458, 598`) and never sees a resource delta; `_relocate` handles one stream
  replacement (`:707`) and assumes non-stream fingerprint inputs are unchanged (`:787-800`).
- Saves: full save uses garbage=1 (`pdf_model.py:1789-1790`); whether it frees unreferenced objects on the
  live handle is UNVERIFIED (probe). After garbage=4, restoring dictionary bytes writes stale xrefs
  (`edit_commands.py:816-821` refuses this for streams). Allocating then detaching objects is not
  document-byte-identical.
- What holds: `/Resources`' own xref is not hashed, so copy-on-write is fingerprint-neutral once reverted.
- Change: a transaction-level record handed to the command (e.g. on `last_commit_outcome`): pre/post
  fingerprints for the whole transaction, ordered writes (undo = stream then remove entry; redo = add
  entry then stream, or the reverse, but specified), rollback of every intermediate failure; page-local
  `/Resources` copy as a DIRECT dictionary in the page object; donors identified by content digest; the
  system donor's object bytes retained and re-created when its xref is gone, else STALE with zero
  mutation; "zero mutation" defined as exact restoration of reachable objects and page behaviour. Tests:
  undo-save-redo; garbage=4 between commit and undo.

### 3. Preview/token pipeline (major; R4)
- Existing token preimage: page fingerprint, splice coordinates, replacement bytes, font identity incl.
  `font_xref` (`plan.py:1172-1194`). A system donor has different xrefs on scratch and live -> token must
  use a content digest, the pre-fingerprint and every splice.
- One preview scratch per session, `render` reverts streams only (`preview.py:240-269, 397-398`): donors
  embedded per keystroke accumulate, names/xrefs drift, every Apply goes `PREVIEW_STALE`. Revert the
  resource delta on the scratch and delete created objects.
- Controller opens a session only when `derive_tier0_preview_target` succeeds
  (`pdf_controller.py:5478-5525`); `PlanPreviewRequest` has Tier 0 fields only (`preview.py:69-93`); the
  engine cache is typed `PreparedEdit` (`engine.py:112`); `PlanPreviewResult` holds one token (the shift
  variant needs a second). Inline Apply without a token returns `PREVIEW_PENDING`
  (`pdf_text_edit.py:4922-4928`), so the three-way dialog must be driven by the PREVIEW's reject reason.
- `bind_paragraph(model, …)` would read the live document from the preview worker thread
  (`preview.py:243-244`): the binder must take a document + a plain paragraph DTO.
- The tokenless hook must sit before the `settings.strict` return (`pdf_text_edit.py:5054-5061`).

### 4. Replay evidence for colour and clip (major; R3, X9-clip)
- `re W W* n g G rg k` are in the lexer's inert alphabet (`pdf_lexer.py:151-153`) and dropped
  (`replay.py:593-599`); adding `ShowOp` fields breaks the coalescing equality contract
  (`pdf_lexer.py:145-147`) or the latency fix. The reference uses `re W* n`, which "a `re W n` chain"
  refuses when read literally.
- A glyph moved to another line keeps its ORIGINAL show's clip: a tight one-line clip hides it. This is a
  fit/admission condition checked before the token is issued, not something to widen.
- Change: `ShowOp` records only the offset of its innermost open `q`; the binder re-lexes
  `[q, op_start)` without coalescing (as `verify.py:1283-1289`); admit `W`/`W*` for a single `re`,
  transformed by the CTM at `re`; require no top-level `W`/colour operators before that `q`.

### 5. Identity from texttrace, verification checks (major; X7, X8, X9, R7)
- PyMuPDF 1.27 texttrace gives the basefont NAME, no font xref, no MCID (`PITFALLS.md:3063-3066`; Codex
  in-memory probe on 1.27.1). (a)(b)(e) "font xref" and (l) are not implementable as worded: identity must
  come from replay (resource -> xref, `mc_stack`) joined to trace `(gid, origin)`; refuse ambiguous joins.
- (h) texttrace line width is never the document pen (`PITFALLS.md:3183-3193`). (i) needs ink boxes from
  `glyph_boxes.glyph_unit_box` (`PITFALLS.md:2992-2997`).
- (j) `TextWriter.append` takes Unicode, not glyph ids, so it cannot reproduce a code whose glyph differs
  from the program's cmap; ARCHITECTURE 10.1.5 is a background-colour sampling rule, not a raster
  tolerance. Use a glyph-id renderer (`mupdf.fz_show_glyph`, S0 probe) with an explicit pixel metric, and
  build the background by suppressing the source shows on a clone (pixel erasure cannot recover an image
  under ink); or exclude image/gradient backgrounds in B.
- (g) must be stated per (source line, new line) pair and exclude pairs separated by a new line break;
  as worded the acceptance edit violates it.
- Still passing wrongly: ragged lines beyond the measure ((f) checks justified lines only); a wrong glyph
  from a non-unique reverse ToUnicode (all of (a)(d)(j) share that mapping) -> add "no line beyond measure
  + 0.3 pt" and "reverse ToUnicode code is unique". Structure READING ORDER is not proven by MCID
  membership (a `/K` order differing from visual order passes).
- Fingerprint closure: structure-tree admission evidence (`/StructTreeRoot`, ParentTree, owner chains,
  `/ActualText` on elements) is outside the existing fingerprint (`marked_content.py:479-549`,
  `inspect.py:811-835`); add a Tier 2R dependency closure, revalidated on apply and on replay.
- `/E` in inline BDC properties is still admitted (`marked_content.py:246-254`).
- Existing code to reuse in the binder: `predict_glyphs` (`glyph_boxes.py:329-402`: Identity-H, Tc, kerns,
  Th), `tj_items` (`:263`), `FontCapability`/`_advance` (`plan.py:291-305`), `glyph_unit_box` (`:704`).
  No simple-font per-glyph walk exists; extend `predict_glyphs` (Tw on code 32). `_GLYPH_MATCH_TOL` lives in
  `pdf_text_edit.py:2723`; move it below `text_commit`.

### 6. Glue (major; R5)
- Gaps BETWEEN shows (CJK-Latin autospacing, the F3 space glyph, the 24 pt gap after the label) are not
  "Tc + kern after the atom" and are lost; the label-to-body gap counts as a break opportunity, so
  justification would move the body start off 104.66.
- Change: glue = next source origin - origin - natural advance for atoms on the same source line; label
  glue fixed and not a break opportunity; body anchored at its start x; allow one `Tc` per emitted line.

### 7. Inserted-character ownership (major X6, minor R12)
- Left-neighbour rule puts body text typed right after `1.` into the `/Lbl` show (and contradicts "label
  touched only by translation"); CJK joining a Latin `/Span` inherits `/Lang en-US`; a whitespace-only F3
  show can become host; with repeated text difflib may align the insertion to the other copy.
- Change: prefer the adjacent show whose font encodes the character and whose structure role/language
  fits; never a label or whitespace-only show; tie-break to the cursor side (the editor must pass the
  caret/edit range, not only old/new text); refuse ambiguous boundaries; verify inserted atoms' owners.

### 8. Paragraph text (major; R8, X10)
- The index uses default rawdict flags (`page_content_text.py:54`); MuPDF may synthesise spaces in the
  label gap or autospace gaps, which would set `space_before` and give `source_text_mismatch` on the
  reference file (UNVERIFIED, S0 probe). Whitespace runs/NBSP/tabs are collapsed (`text_block_parsing.py
  :418, 457-461`).
- `[(Hello) -500 (world)] TJ`: no space glyph but a word gap; "literal source only" yields `Helloworld`.
  Represent literal whitespace and inferred word boundaries separately; inferred ones are synthetic and
  need defined edit semantics.
- A.7's "one space otherwise" breaks the existing hyphen join (`text_block_parsing.py:194-216, 939`,
  D6/Q4). Keep the `-` exception.
- `_RE_NUMBERED_BULLET = ^\d+[.)]\s+` (`pdf_model.py:109`) needs whitespace after the marker; with the new
  joins `1.請…` stops matching. Detect markers on the label run.

### 9. Grouping (major X11, R10; minor R11)
- 2.a falsely splits flush-left prose whose continuation line starts with `3.5 percent`, `2.`, `(1)`:
  also require line i-1 not full or a hard break. Splits go live at S1 with no flag.
- A.4 requires EVERY show tagged; one untagged decorative show disables the veto. Known different owners
  must be an unconditional veto; define mixed/unknown ownership. 2.b looks only at a line's first show.
- A.3 picks the nearest paragraph above first; an incompatible heading can shadow a valid candidate.
  Evaluate ordered candidates; say whether failure stops or continues.
- Two single-line parts (a 2-line item split per line), and ragged-right text, never merge: take the
  measure from the column; same `/LI`/`/P` is a positive cue for two single lines on tagged pages.

### 10. Q2 (major; R6)
- Inheriting Q2 ("shorter or equal replacement: no plan, today's path") sends typo fixes and deletions of
  a multi-show paragraph to the substitute-font rebuild. Tier 2R must handle EVERY edit of a bound
  paragraph; Q2 only decides whether following lines pull up. (Changes an inherited owner answer's scope:
  tell the owner.)

### 11. Slices and tests (major; R9, X12, R13)
- S1 (rule 2.b, merge veto) and the S0 census need the page pass (replay walk, trace join, ParentTree
  lookup) that arrives in S3. Move the page pass into a slice before S1; S3 adds atoms, glue, admission.
- Red tests that pass before implementation: most S1 negative controls, S1 "flag off" guard, S4 forced
  verify failure, S5 "no donor", S5 candidate rejections, S6 "b and c zero mutation", "Tj admitted", "red
  word stays red". Each must set its precondition, assert the Tier 2R stage reached in the chain, and a
  specific reason code.
- Unverified, add as S4 probe: after a show is split across lines, does MuPDF re-segment so that the index
  regroups the paragraph under the same id and B binds it again.

## Handoff for a new session (written 2026-11-14)

Read in this order: `paragraph-grouping-reflow.md` top block and sections 1-3 and 9 (facts and owner
answers, still valid), then this file, then sections 4-6 of the plan knowing where this file overrides them.

Work order: (1) run the six probes below on scratch copies; (2) write revision 3 of sections 4-6 and add a
"round 2 -> revision 3" table like section 10; (3) review round 3; (4) only on CONVERGED start S0.

Owner decisions since revision 2 (already in the plan's section 9 unless noted):
- The shift option is offered only when the band holds nothing but bindable text (confirmed 2026-11-14).
- Q2 scope (in the plan since revision 3, sections 3, 9, C.0): Tier 2R handles every edit of a bound
  paragraph (shorter and equal-length ones too), Q2 only deciding whether later lines pull up. The owner
  said on 2026-11-14 that they do not object.
- Revision 3 is written (plan sections 4-6 and 11). This file stays as the round-2 record.

How the reviews were run (repeat the same way for round 3, both in parallel, read-only):
- `deep-reasoner` with `model: opus`; prompt = the plan path, the exact files and line ranges to check,
  numbered questions, output "numbered findings, severity, plan section, evidence, smallest plan change,
  then CONVERGED / NOT CONVERGED". About 25 minutes and 230k tokens per round.
- `codex:codex-rescue` with `--model gpt-6.1-sol` (the name `6.1-Sol` is rejected); same output format.
- Ask both to mark each row of the previous resolution table RESOLVED / PARTLY / NOT RESOLVED.

The first session's probe scripts are kept in `plans/paragraph-grouping-reflow-probes/` (untracked; they
hard-code object numbers of the private reference file, so decide with the owner before committing them).
Each takes the PDF path, and where it writes output an output directory, as arguments: `probe_fonts.py`
(fonts + stream), `same_face.py` (glyph programs), `probe_premises.py` (hhea, `fsType`, structure tree,
donor), `probe_emit.py` (emission identity), `baseline_edit.py` (repo root, PDF, output dir), `dump_*.py`
(blocks, lines, paragraphs). What each did (run with `.venv\Scripts\python.exe -I`, always on a copy):
- Fonts and stream: `page.get_fonts(full=True)`, each font object and descendant via `doc.xref_object`,
  `FontFile2` via `doc.xref_stream`; content stream decoded as latin-1 and searched around `378.89 Tm`,
  `357.89 Tm`, `336.89 Tm`, `315.89 Tm` (item 1 lines 1-3 and item 2).
- Same glyph programs: fontTools `TTFont(lazy=True)` of the subset, the in-document full face and the
  system face; compare `glyf` bytes per GID (GIDs are retained in the subset) and `hmtx` advances.
- Donor: `doc.xref_set_key(page.xref, "Resources/Font/FDonor", "<xref> 0 R")`, replace one show with
  `BT/FDonor 14.04 Tf 1 0 0 1 x y Tm[<0445>]TJ/F2 14.04 Tf[<..>]TJ ET`, `update_stream`, render, save
  with `garbage=3`, reopen, extract.
- Emission identity: regex over the shows of one baseline, empty each array to `[]`, re-emit in the first
  show's `BT` as `<Tc> Tc/Fk 14.04 Tf 0 g 1 0 0 1 x y Tm[…]TJ`; compare the full-page pixmap at 2x and the
  sorted texttrace `(font, size, unicode, gid, origin)` before/after and after save + reopen.
- Baseline edit: `PDFModel().open_pdf(copy)`, `ensure_page_index_built(1)`, paragraph `pg0_b18_p0`,
  `model.edit_text(1, Rect(para.bbox), new_text, font=…, size=…, color=…, original_text=para.text,
  target_mode="paragraph", allow_rebuild=…, confirm_fallback=…)` with
  `RebuildConsent(acknowledged_glyph_loss=model.pending_rebuild_glyph_loss)` from `model.edit_requests`.
- Structure tree: walk `/StructTreeRoot` `/K` recursively, map MCID -> (element xref, `/S`), read `/P`.

Housekeeping: both plan files and `docs/experiments/opencode-parity/`, `plans/opencode-parity-harness.md`
are untracked; `docs/to_Update.md` is modified. Nothing was committed in this work.

## Probes to run before revision 3 (scratch only) - ALL SIX RUN 2026-11-14; results in plan section 2

Answers in one line each: 1 no (live handle keeps orphans; `garbage>=2` renumbers the live handle); 2 yes
(`synthetic` flag, reference file has none); 3 names identical, no help; 4 ink mask exact, tone not; 5 passes
incl. a second rewrite, kerns must be kept; 6 yes, and reverse-unique. Extra: paragraph ids shift after an edit.

1. Does a garbage=1 full save free unreferenced objects on the live handle?
2. Do rawdict/texttrace expose which spaces are synthetic (trace glyph at the space origin)?
3. Texttrace font names for subset vs full-face donor (prefix stripped?).
4. `mupdf.fz_show_glyph` (or equivalent) renders a given gid of an embedded program.
5. Whole-`BT`-body rewrite identity on the reference file, then a second rewrite of the result.
6. Does the in-document donor's ToUnicode cover the inserted CIDs?
