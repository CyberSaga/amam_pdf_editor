# Paragraph editing like the reference editor: grouping, original-font reflow, line spacing

## Current state and next step (2026-11-14, design revision 9, no product code changed)

- Goal (owner, 2026-11-13): editing a paragraph behaves like the reference video: one visual paragraph is
  one editable unit, typed text re-wraps inside the paragraph, the font does not change, line spacing is
  adjustable. Reference file: a one-page tagged Office PDF in the owner's Downloads folder (`1113/`); it is a
  real meeting record, so it is never committed (acceptance on it is `local_only`).
- Design parts: (A) paragraph grouping in the index, (B) page pass + per-glyph binder, (C) Tier 2R =
  re-typeset the touched lines in the ORIGINAL font resources by rewriting whole `BT … ET` bodies, (D)
  same-face glyph supply, (E) line spacing as a translation.
- This plan IS the "Tier 2R, own plan" that `plans/paragraph-reflow.md` deferred (section 3).
- Owner answers are in section 9. Decisions of 2026-11-14: system donors in v1; a shortened line pulls up
  later lines of the SAME paragraph only; probe scripts committable; the tier is not the point, the font
  must not jump; a font change is never a silent fallback (C.0); when no same-face donor exists ONLY the
  newly typed characters use a substitute font, AFTER v1 (S9, not designed).
- Build order (designer's choice): S0 probes -> S1 page pass -> S2 grouping -> S3 breaker -> S4 binder ->
  S5 Tier 2R stream-only -> S6a donor transaction with the in-document donor -> S6b system donor -> S7 UI
  + activation -> S8 line spacing. Activation (S7) waits for S6b.
- Reviews: rounds 1-6 NOT CONVERGED (sections 10-15; records `plans/paragraph-grouping-reflow-review-r2.md`
  .. `-r6.md`). Since round 5 there is no blocker and the donor transaction is RESOLVED from both
  reviewers; round 6 left only the layout arithmetic of C.3 / C.6 (f)(g) and the list of refusals that
  continue the chain.
- Revision 7 (section 15) defined fit, natural width, legality and the share ONCE in C.3 (C.6 (g) calls
  them), classified outcomes by code, and refused unproven left anchoring (`tier2r:alignment`).
- Round 7 (narrow): NOT CONVERGED from both, 0 blockers (`plans/paragraph-grouping-reflow-review-r7.md`).
- Revision 8 (section 16) fixes the SCOPE of that arithmetic: it applies to laid-out lines only (kept
  lines are checked against source origins); the range starts one line earlier when the break into the
  edited line must be re-decided; a frame change re-breaks every segment; the measure is the largest
  line end, not the page wall; justification needs widened gaps, not coincident ends; left anchoring is
  per paragraph with competing centre/right evidence refused.
- 2026-11-14: `merge/security-remediation` merged (saves write object streams). Probe P9: P1/P7 hold;
  line citations of the merged files were updated.
- Not measured yet (S0 probes, in order): real reflows re-index and re-admit; the emission number format;
  per-glyph threshold `T`; clip vs texttrace; autospacing gaps; ink-box cost; the producer's breaks are
  greedy under C.3. Probe scripts are not committed (allowed, not asked).
- Round 8 (narrow): NOT CONVERGED from both (`plans/paragraph-grouping-reflow-review-r8.md`): one blocker
  (kern-made word gaps entered the share) and majors about telling justification from producer spacing.
- Revision 9 (section 17): ONE definition of what carries justification (share pairs with a last-line
  baseline per class, clamp, uniform-tracking guard; ragged on doubt); `tier2r:hanging_punctuation`;
  anchors and (g) 1 for laid-out lines only; pre-patch exceptions continue as `tier2r:internal_error`.
- Next step: narrow review round 9 on B.1 and C.3 / C.6 (f)(g). S0 only when both say CONVERGED.

## 1. What fails today (model-level baseline, current engine, scratch copy)

Edit: paragraph-mode target `pg0_b18_p0`, insert `（包含測試點位範本）` after `文件範本`.

- Tiered engine: `REJECTED`, chain `tier0:target_reconstruction_unverified`. The index text is
  `1. 請 A 標廠商依照 C 標…` (spaces from `" ".join`, `_make_paragraph_unit`); the stream has no space
  glyph there. Tier 0 builds its own target text (`_tier0_target_from_resolve`), so fixing the index text
  alone does not make this edit commit: a multi-show paragraph refuses `multi_span_target` next.
- Consented rebuild: `DEGRADED_COMMITTED`, chain `(…, legacy)`. Line 1 redrawn with the synthetic spaces
  and running past the right margin; the two continuation lines and item 2 (not targeted) redrawn in a
  sans-serif substitute (`Droid Sans Fallback`, `CharisSIL` in the band). This is the "font jumps".
- Index: item "1." is two paragraphs (`pg0_b18_p0` = line 1, `pg0_b19_p0` = lines 2-3 PLUS item "2.").
- Not measured: the UI path (this baseline calls `PDFModel.edit_text` directly).

## 2. Measured facts about the reference file (PyMuPDF 1.27, fontTools)

- Producer Acrobat Pro DC over a Word export. Catalog has `/StructTreeRoot`, `/MarkInfo<</Marked false>>`.
- Stream shape: one content stream, 124 shows, every one `/Span<</MCID n/Lang…>>BDC q <page clip> re W* n
  0 g 0 G BT [Tc] /Fk size Tf 1 0 0 1 x y Tm [ … ]TJ ET Q EMC`. One `BT`/absolute `Tm` per show; a line is
  5-15 shows (font switch per script). A continuation line's first show sits in the SAME MCID as the
  previous line's last show (a second `q … Q` before `EMC`).
- Fonts on the page: `F1` simple TrueType WinAnsi subset (Latin glyphs of the Kai face), `F2` Type0
  Identity-H subset with a `CIDToGIDMap` stream and its own CID numbering, `F3` ArialMT (space only).
  Text extraction is correct Unicode.
- The `F2` subset lacks glyphs for 包 含 測 試 位 (5 of the 8 inserted ideographs); 點 範 本 （ ） exist.
- Same glyph programs, measured: the 393 non-empty glyph programs of the subset are byte-identical, with
  equal advances, to (a) a full copy of the face embedded in the same document (used by Form XObjects
  `Fm1..Fm10`) and (b) the installed system face (22,087 of 22,087 shared programs equal between (a) and
  (b)). OS/2 `fsType` = 0x0008. Hinting tables (`fpgm`/`prep`/`cvt `) were NOT compared (D requires it).
- Donor premise, PASS: a new `/Resources/Font` entry on the page pointing at the in-document full face,
  showing `<0445>` (GID of 包), renders 包 in the same face on the LIVE handle and after save + reopen
  (MuPDF extracts `15包提`; whether the donor's ToUnicode covers that CID was not checked).
- Multi-`Tm` emission premise, PASS: on line 2 of item 1, seven shows were emptied (`[]TJ`) and re-emitted
  at their own origins inside one `BT` as `<Tc> Tc /Fk 14.04 Tf 0 g 1 0 0 1 x y Tm [ … ]TJ` runs. Full-page
  raster at 2x and the texttrace of all 392 glyphs are identical on the live handle and after save +
  reopen. This proves several `Tm`+`TJ` pairs with font switches inside one `BT`; revision 2 uses the same
  mechanism per show instead of in one host.
- Geometry of item 1: baselines 463.15 / 484.15 / 505.15 (pitch 21.0), size 14.04; first line x0 80.66
  (label `1.`), body and continuation x0 104.66 (hanging indent 24.0); lines 1-2 end at 539.2 / 539.0
  (justified, by `TJ` kerns of -8/-16 and `Tc .24`), last line ends at 335.8. Item 2 starts at 526.15.
- Line-spacing unit: hhea line height (820 + 204 + 204) / 1024 = 1.1992 em; 21.0 / (14.04 x 1.1992) =
  1.247 = the reference editor's "1.25x". Unit = multiples of the font's natural (hhea) line height.
- Structure tree: item 1 = `/LI` with children `/Lbl` (MCID 113) and `/LBody` (MCIDs 115..133); the Latin
  words are `/Span` children of that `/LBody`. Item 2 = `/Lbl` 135 + `/LBody` 137..141 under its own `/LI`.
- Text inside the Form XObjects (attendee names) is out of scope (T16-9, XObject targets).

### What the reference video does (reference editor, 50 s, frames reviewed)

1. Text tool, click into item 1: ONE frame around the whole body; items 1 and 2 are separate paragraphs in
   it. Panel per paragraph: first-line indent 0, hanging indent 8.47 mm (= 24.0 pt, the measured value),
   left indent 8.47 mm, line spacing 1.25x, tab stop 12.7 mm; per character: font, 14.04 pt, colour.
2. Types `（包含測試點位範本）` mid-sentence: the text re-wraps at the frame width, continuation lines
   keep the hanging indent, font and size unchanged, the paragraph stays at three lines, item 2 and the
   headings below do not move.
3. Selects items 1+2: differing values show as "mixed"; line spacing dropdown 1x / 1.15x / 1.5x / 2x; picks
   1.15x: both paragraphs tighten, item 2 moves up, the headings below stay.
4. Leaves the tool: the page looks like the original apart from the edit.

### Round-3 probe results (2026-11-14, scratch copies, PyMuPDF 1.27; scripts `plans/paragraph-grouping-reflow-probes/r3_*.py`)

- P1 saves. `save(garbage=1)` to another path does NOT free unreferenced objects on the live handle (orphan
  object and stream still readable, `xref_length` unchanged); the SAVED file has them as `null`, numbering
  kept, new allocations append (do not reuse freed slots). `tobytes(garbage=0)` keeps orphans. `tobytes(garbage>=2)`
  RENUMBERS THE LIVE HANDLE (live length 4431 -> 3797, page xref 3894 -> 3690, old object numbers invalid:
  `bad xref`). `xref_set_key(..., "null")` leaves `/FDonor null`; `update_object(page.xref, saved bytes)`
  restores the page object byte-equal. `update_object` at a freed slot of a reopened file works and survives
  a further save. Save-over-open reopens the pruned file (`pdf_model.py:5930-5950`).
- P2 spaces. rawdict chars carry `synthetic` (True on a kern word gap and on a small between-show gap on one
  baseline; a wide gap makes separate lines). The reference file is clean: all 4 spaces in item 1/2 have a
  texttrace glyph at their origin (ArialMT / the Kai face), none synthetic. `TEXT_INHIBIT_SPACES` drops the
  synthetic ones. Product code already reads `ch.get("synthetic")` (`pdf_text_edit.py:1917,2770`,
  `text_paint_state.py:973`).
- P3 names. texttrace font name is the stripped basefont (`DFKaiShu-SB-Estd-BF`) for F1, F2 and the donor
  alike: identity cannot come from the trace. The page lists 11 same-named full-face Type0 objects (3966,
  3998, ... 4420), each with its own FontFile2.
- P6 donor 3966. Identity-H, no `CIDToGIDMap`, `/W` for all 22134 glyphs (all 1000 = hmtx), ToUnicode covers
  all 10 inserted characters and the reverse map is unique for each; showing the 10 CIDs gives the right gids
  and extraction returns `包含測試點位範本（）` exactly.
- P4 glyph-id renderer. `fz_show_glyph` + `fz_fill_text` on the embedded programs reproduces the page's ink
  MASK of line 2 exactly (0 mismatches, RGB and gray) but not its tone values (max delta 40-42; cause not
  found, same with one or two text objects). Controls: gid+1 -> 6017 mask mismatches, one glyph moved 0.3 pt
  -> 9. So it is a glyph-IDENTITY check on a plain background, not a position or exact-raster check.
- P5 body rewrite. Whole-`BT`-body rewrite of 17 shows / 87 glyphs of item 1 (two `Tm` runs, then one `Tm`
  per glyph = second rewrite of the result): 2x raster, texttrace (2 dp), text, save+reopen and block/line
  segmentation identical. A first attempt that dropped kerns when splitting moved glyphs 0.02-0.06 pt and
  changed the raster: kerns must stay in each piece and glue must be re-derived from origins. One body with
  glyphs on two baselines and a donor `Tf` switch, runs re-emitted in reverse order: texttrace identical after
  save+reopen. Index effect: moving one glyph to another line splits it into its own block and paragraph ids
  shift (22 -> 23 paragraphs); a synthetic push of line 2 merged blocks (22 -> 21). Ids are NOT stable across an
  edit, and "B binds the edited paragraph again" is NOT proven (probes were synthetic: S4 probe on a real reflow).

### Round-4 probe results (2026-11-14, scratch copies; script `r4_probes_tail_orphan_subset.py`)

- P7 tail orphans. Two unreferenced objects created at the END of the xref table (4430, 4431), then
  `save(garbage=1)` and reopen: `xref_length` is unchanged (4432), both numbers are `null` slots (the table
  is not shortened), `update_object` works at them, `get_new_xref()` returns 4432 (appends), and the new
  object survives a further save. So an equal `xref_epoch` never proves that an unreferenced object exists.
- P8 subset determinism. Subsetting the installed Kai face twice for the same five characters (GIDs
  retained, hinting kept) gives different bytes: only the `head` table differs (modified time, checksum).
  With `TTFont(recalcTimestamp=False)` the two subsets are byte-equal.

### Probe after the security merge (2026-11-14; script `r8_probe_objstm_orphan.py`, synthetic document)

- **P9**: the model's full saves now write object streams (`_save_doc_packed`, `garbage=1`). With
  `garbage=1` + `use_objstms=1` an unreferenced object is still a `null` slot after reopen, surviving
  objects and the page keep their numbers, the table grows by the two container objects, and a new
  object appends past them. P1 and P7 hold unchanged; the donor protocol uses no object number, so
  the containers do not matter to it. `xref_epoch` handling is unchanged by the merge.

## 3. Relation to `plans/paragraph-reflow.md` (F14-VF4-WRAP-REFLOW)

Inherited unchanged: D3 (visual lines = baseline clusters, never `line_idx`), D4 (hard-break inference),
D6 + Q4 (line-end hyphen kept), D7 (convergence: same token on the same baseline -> untouched tail), D10
(justification by placement), D12 (RTL), Q3 (centred single line grows right), Q6 (paragraph-mode edits use
the breaker), Q8 (no line cap), Q9, Q10, and from Q1 the rules "fit is decided before any mutation" and "the
typed text is never discarded" with the code `REFLOW_DOES_NOT_FIT`. D5 (measure) is NOT inherited by Tier 2R except for a
one-line paragraph (C.2); the INDEX uses the column measure of A.1, not `_right_wall`.

Q2 narrowed, then changed. 2026-11-14 (owner did not object): Tier 2R handles every edit of a bound
paragraph, because "shorter or equal replacement: no plan, today's path" would send every typo fix in a
multi-show paragraph to the substitute-font rebuild. 2026-11-14 (owner decision): the layout half of Q2 is
replaced too. A shortened line PULLS UP the later lines of the same paragraph; later paragraphs stay in
place (C.3).

Changed by the owner on 2026-11-13: Q1's two-way offer becomes the three-way choice of C.4 (moving the
paragraphs below was rejected on 2026-10-12 for the substitute-font rebuild; accepted now as a translation
in the original font). D21 (a dragged edit never reflows) no longer holds for paragraphs Tier 2R binds (C.8).

Superseded for paragraphs Tier 2R can bind: Slices 1-3 (reflow through the consented rebuild in a
substitute font), D9, D11, Q5. They stay on file as the fallback design and are not scheduled (OD-1).

## 4. Design (revision 9)

Terms used below.
- **Body**: one text object `BT … ET`. A body is *rewritable* when all of this holds: it is the only text
  object of its innermost `q … Q` scope and nothing but whitespace lies between `ET` and that `Q`; between
  the `q` and `BT` there are only colour operators (`g G rg RG k K`) and at most one clip of the form
  `re W n` or `re W* n` (one rectangle); inside the body there are only `Tc Tf Tm Tj TJ Tw Tz`; every `Tm`
  is `1 0 0 1 x y`; EVERY show follows its own `Tm`, with nothing but `Tc Tf Tw Tz` between that `Tm` and
  the show (two shows after one `Tm` are not admitted in v1: the replay does not carry the cursor from one
  show to the next, `replay.py:564-586`, `glyph_boxes.py:361`; Tier 2R's own output always meets this, each
  run having its `Tm`); the CTM at the body is the identity; a `Tf` precedes its first show; and at EVERY show
  of the body the effective text state (replay, inherited values included) is `Tw` 0, `Tz` 100, rise 0,
  render mode 0. A body may hold any number of shows, so the output of an edit is admissible again.
- **Run**: one emitted `[<Tc> Tc] [/F size Tf] 1 0 0 1 x y Tm [ … ]TJ` inside a body.
- **Atom**: one glyph of the paragraph (B). An atom never leaves its body: the body owns its marked-content
  sequence, structure element, clip, colour and `q` scope.
- **Lead-in** of an atom: the gap in front of it on its source line (B.1). A gap belongs to the atom on its
  RIGHT; the first atom of a source line has none.
- **Page pass**: the per-page read-only analysis of B.0, shared by grouping, binder, census and verify.
- **Segment**: the lines of a paragraph between two hard breaks (or the paragraph ends).

### A. Paragraph grouping (index; `model/paragraph_grouping.py`, called from `_build_paragraphs`)

`_build_paragraphs` stays the only producer of `EditableParagraph`. The pass runs after the per-block build
and before `_merge_vertical_paragraphs`, on horizontal LEFT-TO-RIGHT paragraphs from a block with ONE column
group (cell-split blocks, ARCHITECTURE 10.3, stay as today). A paragraph holding any right-to-left run is
not touched by A at all in v1 (no split, no merge, today's text composition), and B refuses it
(`tier2r:rtl`); this is a stated v1 limit, not a mechanism. Everything in A (splits, merges, text
composition) is behind ONE setting `TextCommitSettings.paragraph_grouping`, default off until S7; with it
off the index is byte-for-byte today's.

1. Visual lines: cluster runs by baseline (D3). **Column measure**: over all lines of the page's paragraphs
   that x-overlap the candidate by at least 50 % and have its size (0.5 pt), the largest x1 that at least
   two lines reach within 1 pt; none -> no measure. With a measure a line is **full** when the first word
   (Latin/digit word, or one CJK character plus any closing punctuation bound to it) of the NEXT line
   would not fit between its x1 and the measure, and **short** otherwise. With no measure a line is
   neither: fullness is UNKNOWN, and every rule below says what unknown means.
2. Split inside a block-paragraph before line i (any one suffices):
   a. line i starts with a list marker, its x0 is at most the paragraph's first-line x0 + 1 pt, AND one of:
      (i) line i-1 is short (known) or ends with a hard break (D4); (ii) **sibling item**: the paragraph's
      first line starts with a marker of the same class at the same x0 (1 pt). Marker = the line's first
      run matches the marker pattern (`_starts_bullet_item` extended with `(1)`, `1)`, `a)`, `1.1`, `一、`,
      `（一）`, `①`) and is followed by whitespace, by a gap of at least 0.5 x size, or is a tagged `/Lbl`.
      Marker class = the pattern that matched. The whitespace-bound `_RE_NUMBERED_BULLET`
      (`pdf_model.py:109`) is not used here. Consequences, each a test: an untagged list whose item 1 ends
      with a FULL line still splits before `2.` (ii); a flush-left prose continuation line starting
      `3.5 percent` does not split, with a measure (line i-1 full) and without one (unknown, and the
      paragraph's first line has no marker); the same line in a first-line-indented paragraph does not
      split either (no marker on the first line). Stated limit: a lone marker line after a full or
      unknown line of a paragraph that does not itself start with a marker stays fused.
   b. owner split (A.4): the owner sets of lines i-1 and i are both non-empty and disjoint.
   c. line i-1 ends with a hard break AND line i's x0 differs from line i-1's by more than 1 pt AND the
      lines share neither a centre nor a right edge within 1 pt AND the owner sets of the two lines are
      not equal-and-non-empty (one tagged paragraph with a hard break inside stays whole).
   Poetry-like text (hard breaks, same x0, no marker) is not split.
3. Merge B into A. The only candidate A is the paragraph owning the closest line above B's first line among
   lines that x-overlap B's first line by at least 50 %; when A fails any condition there is no merge (a
   farther paragraph always has A's line in between). Paragraphs are visited top to bottom, so chains
   merge. ALL must hold: same rotation, both left-to-right; same dominant font family and size within 0.5
   pt; B's first line does not start with a list marker (2.a definition); A's last line is full, OR
   fullness is unknown and the owner sets of A's last line and B's first line are equal and non-empty;
   baseline step A.last -> B.first equals the pitch within 5 % (pitch from whichever of A/B has two lines;
   both single lines: the step is between 1.0 and 2.0 x size AND the owner sets are equal and non-empty,
   otherwise no merge); B.x0 equals A's continuation x0 within 1 pt, or A is one line and B.x0 equals A.x0
   or the x where A's text starts after its marker; no drawing and no other paragraph lies between the two
   lines; no same-baseline sibling of either line at a disjoint x; the owner sets are not known-different
   (A.4); when BOTH owner sets are empty, A's last line, after trailing closing brackets and quotes
   (`」』）〕】》〉"')]`) are stripped, does not end with sentence-final punctuation (`。．.！？!?：:`).
   Geometrically indistinguishable cases merge; documented; the breaker treats the join as a soft break.
   Stated limit: on an untagged page with no column measure nothing merges.
4. Owner evidence (tagged pages; from the page pass, built lazily only when rule 2/3 has a candidate). The
   **owner set** of a line = for each of its shows that sits in an MCID, the nearest ancestor whose
   structure type, after `/RoleMap` resolution, is one of `/P /LI /H /H1 … /H6 /TD /TH /Caption /TOCI`;
   untagged and `/Artifact` shows and shows with no such ancestor contribute nothing. Known-different
   (both sets non-empty and disjoint) is an unconditional merge veto and the split cue 2.b; one empty set
   = unknown = geometry alone decides; overlapping but unequal sets = no veto, no positive cue. Equal
   non-empty sets are the positive cue of rules 2.c and 3.
5. Identity. Paragraph ids are derived from block numbers and are NOT stable across an edit (probe P5).
   Nothing may keep a paragraph id across a mutation: after every commit, undo or redo the page index is
   rebuilt and consumers re-resolve by position. `EditOutcome` gains `paragraph_anchor` (page, origin of
   the first non-label atom after the edit); the Controller re-selects with `paragraph_at(page, point)`.
   Commands hold stream patches, never ids. Within one index build: a merged paragraph keeps the
   `paragraph_id`/`block_idx` of its FIRST constituent and gains `constituent_block_ids`; a split keeps
   `_p0` on the block's first paragraph (pinned rule) and numbers the rest upward. Consumers in
   `model/pdf_text_edit.py` that take one block from `para.block_idx` (`_resolve_edit_target`: no-change
   check, rebuild base box and width, redaction fallback, glyph-loss and marker fallbacks) use the union
   for a multi-constituent paragraph.
6. Paragraph text (left-to-right paragraphs only). Built from rawdict characters, per visual line, in x
   order:
   - a character with a glyph is kept (whitespace included; runs of whitespace collapse to one space as
     today, the collapsed run is ONE text position mapping to all its atoms);
   - a rawdict character flagged `synthetic` (probe P2: kern word gap, small between-show gap) is kept as
     one space and recorded in the `inferred_ws` mask;
   - lines are joined with nothing when both sides are CJK or CJK punctuation; with nothing after a
     line-end hyphen exactly as today (`text_block_parsing.py:194-216`, D6/Q4); with nothing when the
     upper line already ends in whitespace (`:208-213`); with one space otherwise; with a newline at a
     hard break. Every join character is recorded in the `join_sep` mask.
   `inferred_ws` and `join_sep` positions have no atom (B, C.1). No gap threshold is added by the index.

Negative controls for S2 (each in a fixture that ALSO holds a positive merge or split, asserted in the same
test, so the test fails before the implementation): heading `五、…` -> `A/C標…`; `六、決議事項` -> item 1;
item 1 -> item 2; the spacer lines under `八、`; a centred two-line title; a right-aligned block; a narrow
table column of one-word cells; a label-over-value form; a bold heading over body text at the same indent
(tagged `/H1` over `/P`: known-different); two paragraphs separated by a rule; flush-left prose with a
continuation line starting `3.5 percent`, with and without a measure, and in a first-line-indented
paragraph; a sentence ending `。」` over a new paragraph on an untagged page; one untagged decorative show
beside two differently-owned lines (veto still applies); a right-to-left paragraph (index unchanged).
Positive controls: an untagged list whose item 1 ends with a full line splits before `2.`; two same-owner
single lines merge on a page with no measure.

### B. Page pass and paragraph binder (Qt-free, read-only, take a `fitz.Document`, never the model)

**B.0 Page pass** (`model/text_commit/page_pass.py`, new). Its result is plain data (no document handle, no
PyMuPDF object), cached per document object and keyed by the page fingerprint; the preview worker's scratch
and the live document each fill their own cache, and equal fingerprints give equal results.
- Replay (`replay_page_streams`); `ShowOp` gains ONE field, `q_open_offset` (offset of its innermost open
  `q`, -1 at top level), which keeps the lexer's coalescing contract. The pass also lexes the stream ONCE
  without coalescing (as `verify.py:1283-1289`; the coalescing lexer hides operators, `replay.py:593-599`,
  `pdf_lexer.py:151-153`) and records for every `q` scope the state operators at its own depth. For each
  body it records: byte range; the **clip chain** = the clip of every scope open at the body, innermost to
  top level; the entry text state (`Tc Tw Tz Tf`, rise, render mode) from the replay; whether the body is
  rewritable (section 4 terms).
- **Effective clip** = the intersection of the clip chain's rectangles. It is proven only when every
  `W`/`W*` in an open scope has the form `re W n` / `re W* n` and no `cm` and no `gs` appears in any open
  scope; otherwise the body is `unproven_outer_state`. Colour operators in outer scopes need no proof: a
  body is rewritten in place, so the graphics state it inherits at `BT` is the state it had, and check
  C.6 (h) compares the traced colour before and after.
- Glyph prediction: `predict_glyphs` (`glyph_boxes.py:329-402`) extended to simple fonts (`Widths` /
  `FirstChar`), reusing `tj_items` and `FontCapability`. The code -> gid route of a simple font is
  `SimpleFontProgram.route_gids` (`simple_font_programs.py:353`); when its routes do not agree on one gid
  the show is unbound. `_GLYPH_MATCH_TOL` moves from `pdf_text_edit.py:2723` to `glyph_boxes.py` and is
  imported back.
- Trace join: texttrace gives the basefont NAME only (probe P3; no font xref, no MCID). Each predicted
  glyph (gid, origin) is joined to exactly one trace glyph with the same gid, an origin within tolerance
  and the resource's stripped basefont name. Font xref and MCID come from the replay (resource table,
  `mc_stack`). No partner, or two partners (overprinted duplicates): the show is unbound and a paragraph
  containing it refuses `tier2r:ambiguous_glyph_join` / `tier2r:show_unbound`.
- **Ink box** of a glyph = the bounding box of its mask from the glyph-id renderer (`mupdf.fz_show_glyph` +
  `fz_fill_text`, probe P4) at 2x, grown outward to whole pixels, cached per (font program digest, gid,
  size). One source for C.4, C.6 (i) and C.6 (j); `glyph_boxes.glyph_unit_box` (raw `glyf`, refuses
  point-matched composites, `glyph_boxes.py:660-662, 732-749`) is not used by Tier 2R, so a hinting-
  dependent face cannot make the box disagree with the rendered ink. Whitespace atoms have no ink box.
- Owner lookup: MCID -> structure element -> owner chain up to the root, from the page's ParentTree entry.
  It is recomputed on every use (never cached), because the walk IS the **structure closure** (C.7).

**B.1 Binder** (`model/text_commit/paragraph_source.py`, new). `bind_paragraph(doc, page_index, target)` ->
`ParagraphSource` or a refusal. `target` is a plain DTO (`ParagraphBindTarget`: line boxes, run origins,
text, masks) built by the model from the index, so the preview worker never reads the live document.
- `GlyphAtom`: body id, index in body, font resource + xref, code bytes, Unicode (strict ToUnicode / simple
  encoding), natural advance (PDF width table), origin, size, `Tc` in effect, source array id and index,
  `lead_in`, `array_linked` (the previous atom is the previous glyph of the SAME source array), the
  **kern slot** (the numeric items between the two glyphs in that array, possibly none), role (`label` /
  `body` / `space`). A whitespace atom may have an empty glyph; it needs a width entry.
- Lines: baseline clusters (D3). Reading order = line, then x. Admission requires that the bodies of the
  paragraph appear in the stream in reading order of their first atoms (`tier2r:stream_order`).
- **Lead-in** (geometric): `lead_in(b)` = origin x of b - origin x of the previous atom a on the source
  line - natural advance of a, whatever bodies a and b are in (so `Tc`, `TJ` kerns, the F3 space glyph,
  CJK-Latin autospacing and between-body gaps are all kept). A **pair** (a, b) is a break opportunity
  between two CJK atoms, after a whitespace atom, at an `inferred_ws`, at a surviving `join_sep` (the
  pair across a former line end, atom-less or not), and after an existing line-end hyphen (Q4); never
  inside a Latin/digit word. The label and the lead-in of the first body atom are
  fixed: not an opportunity, never justified; the body start x of the first line and the continuation x0
  are anchors (C.2).
- **Justification share** (all sums over the C.3 content of a line, trailing whitespace excluded). The
  rule of this bullet: on doubt the paragraph is RAGGED (share 0), which keeps the producer's spacing.
  - **Share pair** = a pair that can carry justification: a CJK/CJK pair (class `cjk`) or a pair after a
    whitespace ATOM (class `space`). An `inferred_ws` pair and a `join_sep` pair are break opportunities
    only, NEVER share pairs: their gap is the producer's own word gap (`TJ` kerns), so their intrinsic
    lead-in is the source lead-in and no share is ever taken from or added to them.
  - **Baseline** `base(c)` of a class = median lead-in over the class's share pairs on the segments' LAST
    lines (never justified, so nothing is circular). It is the producer's tracking for that class. A
    class with no share pair on a last line has NO baseline (there is no 0 fallback).
  - `share_src(line)` = max(0, mean over the line's share pairs of (lead-in - `base(class)`)); 0 when the
    line has no share pair. The clamp keeps compressed producer gaps in the intrinsic lead-in.
  - A paragraph is **justified** when ALL hold: (1) every class that occurs on a non-last line has a
    baseline; (2) at least one non-last line has a share pair; (3) the ends (advance end of the last
    non-whitespace atom) of all non-last lines agree within 0.3 pt; (4) at least half of the non-last
    lines that have a share pair (and at least one) have `share_src` > 0.02 pt; (5) the widening is not
    uniform tracking: NOT (every atom of the non-last lines has one `Tc` T1, every atom of the last
    lines one `Tc` T0, and on every non-last line |`share_src` - (T1 - T0)| <= 0.02 pt). Otherwise the
    paragraph is ragged. Coincident line ends, tracked text, a CJK grid, kern-made word spaces and a
    last line without share pairs are therefore all ragged.
  - In a ragged paragraph `share_src` is 0 for every line; in a justified one it is the value above for
    non-last lines and 0 for last lines. **Intrinsic lead-in** = `lead_in` - `share_src(line)` at a SHARE
    pair, `lead_in` everywhere else. The producer's uneven spread (`Tc .24` on some shows, kerns -8/-16
    on others) stays in the intrinsic lead-in as it is.
  - `opp_cjk` (join rule of C.1) = `base(cjk)`; without one, the median CJK/CJK lead-in over all lines of
    a ragged paragraph, else undefined.
  Known limit: a justified paragraph whose producer spread every line by one uniform `Tc` and whose
  lines happen to share the same amount is ragged by (5); its re-laid lines are not stretched.
- Text check: the atoms' Unicode in reading order equals the index text with `inferred_ws` and `join_sep`
  positions removed and the same whitespace collapse applied (`tier2r:source_text_mismatch`).
- Marked content (`admit_tier2r_wrappers` in `marked_content.py`; `admit_show_wrappers` stays for Tier
  0/1). Admitted: default-visible optional-content layers, structure-content wrappers (`MCID`, optional
  `/Lang`). Refused: ActualText, Alt, `/E` (inline properties too, today admitted at
  `marked_content.py:246-254`), Artifact, hidden or unresolved layers, OCMD, malformed pairing; an owner
  chain containing `/Link`, `/Note`, `/Reference`, `/Annot` or carrying `/ActualText`, `/Alt`, `/E`.
  Every splice is one whole body, hence inside its wrapper and its `q` scope.
- v1 admission (each failure `tier2r:<reason>`, zero mutation, chain continues): every body holding an atom
  of the paragraph is rewritable and holds atoms of this paragraph only; no body is
  `unproven_outer_state`; one content stream, not shared with another page; not inside a Form XObject;
  not Type3; page `/Rotate` 0; horizontal, left-to-right only (`tier2r:rtl`); left anchoring proven
  (`tier2r:alignment`) and no hanging line-end punctuation (`tier2r:hanging_punctuation`), both below; no ExtGState applied in scope; no annotation or widget rect meets the paragraph band; **uniform band background**: no image,
  shading or drawing meets the band and the band rendered on a scratch clone (built with the KEEP
  serializer, `preview.py:164-198`) with the paragraph's bodies emptied is one colour
  (`tier2r:band_background_not_uniform`; needed by C.6 j).
- **Left anchoring** (v1 lays every line out from a LEFT anchor; centred and right-aligned text is S9).
  F = the paragraph's first line, C1..Cn = ALL its other lines, whatever their segment. start(F)
  is the x0 of the first BODY atom (a label is not part of it). Proven when:
  - n = 0: a one-line PARAGRAPH keeps its start x and grows to the right (Q3, owner-confirmed).
  - n >= 1: the starts of all Ci agree within 0.3 pt (one continuation x0), AND there is no competing
    evidence: when start(F) differs from the continuation x0 by more than 0.5 pt, neither the midpoints
    of ALL lines nor the ends of ALL lines may agree within 0.5 pt (centred `[30,70] [0,100] [0,100]`
    and its right-aligned twin are refused).
  - n = 1 needs one more proof, because one continuation line proves no edge: the paragraph has a
    label, or start(C1) = start(F) within 0.3 pt, or start(C1) equals (0.3 pt) the continuation x0 of
    another paragraph of the page that is proven left-anchored by the n >= 2 clause and overlaps this
    one in x (the column's left edge is evidenced there). The bind target DTO carries these
    neighbour starts (`column_starts`, built by the model from the index; `bind_paragraph` sees one
    target only).
  Anything else is `tier2r:alignment`: centred or right-aligned text, a centred block of hard-break
  lines (A.2.c keeps it in one paragraph; its lines do not share a start), and two-line shapes with no
  evidence. The rule admits on proof and refuses on doubt, so a wrong call costs a refusal that keeps
  the font (Tier 0/1, today's behaviour), never a layout from the wrong anchor. A paragraph that
  shrinks from three lines to two may be refused on its next edit; that is the same safe outcome.
  Reference item 1: label, continuation starts 104.66 / 104.66, body start 104.66: admitted.
- **Hanging punctuation.** Some producers let a line-end `，` or `。` hang past the margin; that line's
  end is then not the measure. Refused `tier2r:hanging_punctuation` when the largest line end belongs
  to exactly ONE line, that line's last content atom is in the no-line-start set, the next-largest end
  among the other non-last lines is more than 0.3 pt smaller, and the line's end WITHOUT that atom is
  not beyond that next-largest end + 0.3 pt (so only the punctuation protrudes). A widest line that
  would still be the widest without its final punctuation is ordinary ragged text and is admitted.
  Counted in the S4 census. Reference item 1 (539.2 / 539.0): admitted.

### C. Tier 2R plan, emit, verify (`model/text_reflow.py` breaker; `model/text_commit/retypeset.py`)

0. Scope and chain order. Tier 2R handles EVERY edit of a bound paragraph: insertion, deletion,
   replacement, equal length. When the edit has a paragraph bind target, Tier 2R is tried FIRST, in the
   preview worker and in `edit_text` alike; a `tier2r:<reason>` admission refusal continues to Tier 0/1
   and then to today's chain. (Tier 0 first would give two behaviours for one gesture: a deletion inside
   one show would not pull text up, the same deletion across two shows would.) An edit without a
   paragraph bind target follows today's chain unchanged. Owner 2026-11-14: which tier commits is not the
   point, the font must not jump; so the order adds no mechanism beyond "first tier that proves the edit".
   **Explicit restyle.** Tier 2R keeps the source paint, font and size. A request whose `style_overrides`
   change any of them (`preview.py:80`; Tier 0 refuses the same way, `plan.py:1889`,
   `pdf_text_edit.py:4733`) is the admission refusal `tier2r:restyle_requested`, in the preview worker and
   in live planning alike, and the chain continues as today. The overrides are part of the token preimage,
   so a `t2r:` token issued without them is `PREVIEW_STALE` when they are present at Apply.
   **No silent font change (owner 2026-11-14: "other software does not do this").** Three outcomes only,
   classified by CODE, not by phase:
   (1) Every `tier2r:<reason>` refusal continues to Tier 0/1, which keep the font. The reasons are the
   B.1 rules (`alignment` included), `restyle_requested`, `hard_break_edit`, `no_insert_owner`,
   `glyph_unavailable`, `unbreakable_overflow` (C.3), `clip_too_tight` (C.4), and `internal_error` = an unexpected exception
   inside Tier 2R BEFORE a patch set exists (renderer, texttrace, fontTools; logged; Tier 0/1 may still
   edit the paragraph in the same font). All of them are raised
   BEFORE a patch set exists, at binding or during planning, with zero mutation. This is the rule of
   the preview and tokenless paths; at Apply a refusal of the live re-plan is `PREVIEW_STALE` (C.7).
   (2) Terminal (nothing applied, the typed text stays in the editor, the chain does not continue):
   `REFLOW_DOES_NOT_FIT`, `PREVIEW_STALE`, and `tier2r_commit_failed` = any failure once a Tier 2R patch
   set exists (apply, verify C.6, rollback proof), with or without a token. The rebuild is not offered
   for them (S7: reason strings `reflow_does_not_fit` and `tier2r_commit_failed` join `_NOT_REBUILDABLE`,
   `view/text_edit_reasons.py:149-158`; `preview_stale` is there).
   (3) Only when Tier 0/1 refuse too does today's consented rebuild remain, and it never runs without
   the user's explicit consent. Today's sentence already names the font ("字型、字距或相鄰排版可能改變",
   `pdf_controller.py:3762-3763`) and the default button is No (`view/message_boxes.py:42-52`); S7 pins
   both with a test and changes neither. A font change is therefore always the user's choice, never a
   fallback. Which paragraphs still end in (3) is measured by the S4 census (shapes outside v1
   admission; a missing glyph whose face is neither in the document nor installed).
1. Edit mapping. Old text = index text. The common prefix and common suffix of old/new are trimmed; inside
   the remaining span `difflib.SequenceMatcher(autojunk=False)` keeps equal blocks. When the changed span
   can slide (repeated text), the request's `edit_caret` (offset in the new text just after the last typed
   character; new optional field of the edit request and of `PlanPreviewRequest`, sent by the editor)
   picks the position ending at the caret; without it the leftmost position is used. Kept positions keep
   their atoms (font resource and code untouched).
   **Mask positions.** A surviving `inferred_ws` stays a gap (the lead-in of the atom after it). A deleted
   `inferred_ws`: the lead-in of the atom after it becomes that body's `Tc`. A surviving `join_sep` whose
   two neighbours end up on DIFFERENT new lines stays atom-less; one whose neighbours end up on the SAME
   new line is materialized as an inserted space atom (rules below), because an atom-less gap would
   depend on the extractor inferring a space. A deleted or replaced space `join_sep` is an ordinary edit. An edit that inserts or deletes a
   NEWLINE (a hard break) is the v1 admission refusal `tier2r:hard_break_edit`: the re-break never
   crosses a hard break (C.3), so such an edit would commit with the layout unchanged and be lost.
   **Owner of an inserted character**: candidates are the bodies of the atom before and after the insertion
   point. Excluded: a body holding a `label` atom (or owned by `/Lbl`) and a body holding only `space`
   atoms. Order: a body whose own fonts encode the character; a body whose `/Lang` (BDC property or owner
   element) fits the character's script class; the caret side (left). No candidate left ->
   `tier2r:no_insert_owner`. When the only candidate has a non-fitting `/Lang`, it is used and the outcome
   records `lang_mismatch` (known structural footprint, no visual effect). The new atom takes the body's
   size, `Tc` and paint.
   **Font of an inserted character**: first of [the owner body's fonts, other fonts of the paragraph in
   order of use, a donor (D)] where the character has a code with a width entry and a ToUnicode/encoding
   entry, a non-empty glyph (whitespace is exempt: `glyph_boxes.py:720-721` refuses an empty glyph
   today, Tier 2R allows it for U+0020 and U+3000 only), AND the reverse mapping is unique (no second code
   of that font maps to the same character with a different glyph). None -> `tier2r:glyph_unavailable`.
   **Lead-ins after an edit** (a gap stays with the atom on its right): an inserted atom's lead-in is its
   body's `Tc`; the old atom that follows an insertion keeps its own intrinsic lead-in; after a deletion
   the next surviving atom keeps its own intrinsic lead-in. Two atoms that were on different source lines
   and are now adjacent: the right one's lead-in is `opp_cjk` (its body's `Tc` when undefined) for a
   CJK/CJK pair, and its body's `Tc` after a whitespace atom or a line-end hyphen. Stated limit: inserted
   text gets no CJK-Latin autospacing of its own; it keeps the autospace gap that was on its right.
2. Layout properties (`detect_layout`), all from SOURCE geometry: measure (= the largest line end of the paragraph's source lines, which for a justified paragraph
   is the shared edge; NOT D5's `_right_wall` fallback, which would stretch a paragraph to the page
   wall when its widest line is edited; a one-line paragraph alone keeps D5's fallback, Q3/Q10; or the
   dragged box, C.8; stated limit: in a ragged paragraph text typed on the widest line wraps even
   when the column has room to its right),
   label x0, first-line body x0, continuation x0 (= each source continuation line's OWN start: a
   laid-out line that takes the baseline of source line i is anchored at source line i's start, so
   nothing shifts sideways; a line beyond the source count uses the last continuation line's start,
   or the first-line body x0 when there is none), baselines, pitch (median baseline step; a one-line
   paragraph uses the dominant font's hhea line height x size, 1.2 em when unreadable), alignment, hard
   breaks.
3. Breaker (`model/text_reflow.py`). **The definitions of this item are the only ones.** The breaker,
   C.5 and C.6 (f)(g) call the same functions (`line_metrics`, `break_is_legal`, `break_lines`); no other
   item restates them.
   - *Effective geometry*: the source anchors, baselines and measure after the C.8 frame change (the
     identity when the box was not dragged). Every "source" anchor, baseline or measure of C.3-C.6 means
     this.
   - *Scope.* **Laid-out lines** = the lines of the re-broken range (below). Fits, share, gap and
     `break_lines` apply to them ONLY. Every other line of the paragraph (before the range, converged,
     rigidly translated) is a **kept line**: its atoms keep their source origins (plus the one
     translation), its source share and its bytes where possible (d = 0, C.5); no C.3 arithmetic is
     applied to it, so a producer line with compressed or oversized gaps is never re-judged.
   - *Line*: atoms in reading order. Its **content** runs from the first atom to the last non-whitespace
     atom. Whitespace atoms after the content **hang**: they stay in their body, are placed after the
     content at their own intrinsic lead-in, are never counted and never justified.
   - `ilead(a)`: the intrinsic lead-in of atom a given its left neighbour on the NEW line (C.1 rules).
   - **Natural width** = natural advances of the content atoms + `ilead` of the content atoms EXCEPT the
     first (the first atom sits on the line's anchor; the label gap is fixed, B.1).
   - **Available width** = effective measure - the line's anchor x.
   - **Opportunities** of a line = the B.1 opportunity pairs inside its content (they decide where a
     line may break). **Share pairs** of a line = the B.1 share pairs inside its content (they alone
     carry justification; a materialized `join_sep` space atom makes the pair after it a share pair).
   - **Legal break** before atom b: the pair (previous atom in text order, b) is a B.1 opportunity, b is
     not in the no-line-start set (`、。，．：；！？）」』】〕` and closing brackets), and the last non-whitespace
     atom before b is not an opening bracket. A hard break is always a break and is never moved.
   - **Unit** = the atoms from one legal break to the next (trailing whitespace included; it hangs when
     the unit ends a line).
   - **Fits**(L, U) = natural width of the line "L followed by U" <= available width + 0.3 pt (the
     tolerance of B.1's justified test). "L followed by U" is formed by the C.1 rules: L's hanging
     whitespace becomes interior and is counted, an atom-less `join_sep` between L and U is materialized
     as a space atom, U's first atom takes its join lead-in. The first unit of a line is always placed;
     when it does not fit alone the plan refuses `tier2r:unbreakable_overflow`. A unit with no content
     (whitespace only) never starts a line: it always joins the current line and hangs.
   - `break_lines`: greedy first-fit over units. A unit goes on the current line iff it fits, otherwise
     it starts the next line.
   - **Share** of a laid-out line (which line is justified) = slack / share pairs, with slack = max(0,
     available width - natural width), when ALL of these hold: the paragraph is justified (B.1); the line
     ends at a soft break (it is not the last line of its segment); share pairs >= 1; slack / share pairs
     <= 0.5 em (em = the font size of most of the line's content atoms). Otherwise the share is 0, with
     no division when there is no share pair. So a ragged paragraph never gains justification, the last
     line before a hard break or the paragraph end is never stretched, and a line whose gaps would
     exceed half an em stays ragged.
   - **Gap** in front of atom a on a laid-out line = `ilead(a)` + the line's share at a share pair inside
     the content, `ilead(a)` elsewhere (an `inferred_ws` or `join_sep` pair keeps its source gap).
   **Re-break range (owner 2026-11-14: pull-up inside the paragraph).** Every edit re-breaks from the **range
   start** to the end of that line's segment. The range start is the first edited line E; it is the
   line BEFORE E (same segment) when the break into E must be re-decided, i.e. when the break before
   E's new first atom is not legal (a deleted first glyph leaves `，` at the line start) or E's new
   first unit fits (C.3) on the previous source line (a deleted long first word). One step back is
   enough: the line before that is unchanged and so is the unit that follows it. When the range
   starts at E the break into E is the source's own and is kept. When E is left with no atom at all (its whole text deleted) the
   range starts at the line before it too, so that line is laid out again as a last line. This holds whether the edit lengthens or shortens: a shortened line
   takes words from the next line when they fit. A hard break is never crossed. Convergence (D7) is
   tested only for a new line that starts AFTER the whole changed span (every inserted, deleted or
   replaced position lies on an earlier new line): when that line holds exactly the atoms of one source
   line, in order, starting on the same baseline at the same x, the re-break ends; it and all later lines
   are untouched. The edited line itself never converges. **Frame change (C.8).** When the AVAILABLE WIDTH of
   any line differs from the source (right or left edge dragged; a translation changes none), EVERY
   segment is
   re-broken from its first line and nothing converges, also when the text is unchanged (a request
   with unchanged text and a changed rect is a Tier 2R edit, not `GEOMETRY_OVERRIDE_PRESENT`). A pure
   move has precedence and re-breaks nothing: every line is a kept line translated by (dx, dy); a move
   together with a text edit uses the ordinary range on the translated geometry. Section E (line
   spacing) changes baselines only.
   **Baselines.** New line i of the re-broken segment takes the (effective) source baseline of the segment's line i;
   lines beyond the source count continue at `previous + pitch`. When the segment ends with k fewer or k
   more lines than before, every later line of the SAME paragraph is translated rigidly by k x pitch (up
   or down): its bodies are rewritten with only the `Tm` y changed, as in E. Lines of other paragraphs
   never move on a shortening edit: the space freed below the paragraph stays empty (owner 2026-11-14).
   Growth is C.4.
4. Fit (owner 2026-11-13/14). Floor = top of the nearest object below the paragraph whose x-range overlaps
   it (glyph, drawing, image, annotation, widget, Form XObject), or the bottom of the CropBox when
   nothing lies below (growth off the page is `REFLOW_DOES_NOT_FIT`, not a verify failure). Lowest planned line above the floor: the
   paragraph grows down. Otherwise the preview result is `reject_reason=REFLOW_DOES_NOT_FIT` with a
   **growth offer** (C.7) that may hold a **shift variant** token: the consecutive paragraphs below in the
   same column (x-overlap at least 50 %, each starting within two pitches of the previous one's last line)
   move down by the growth; it exists only when the shifted band holds nothing but text that B binds and
   the last shifted line stays above the next floor and inside the CropBox. Every planned glyph's ink box
   (B.0) must lie inside its body's effective clip; a tight one-line clip that would hide a moved glyph
   is the refusal `tier2r:clip_too_tight`, raised before any patch set exists; the chain continues (C.0). A shortening edit always fits.
   Dialog (zh-TW; default and Esc = back to editing), opened by the Controller from the growth offer:
   a. 「把下方段落往下平移」 (only when the offer holds a shift token) -> `edit_text` with that token;
   b. 「退回繼續編輯」 -> nothing applied, editor stays; c. 「取消編輯」 -> nothing applied, editor closes.
   `REFLOW_DOES_NOT_FIT` is terminal everywhere, tokenless callers included: it never continues to Tier
   0/1 or to the consented rebuild.
5. Emit: one `PatchSet` on one stream; each splice replaces ONE whole rewritable body (`BT` to `ET`). Bodies
   with no touched atom are not spliced, so they and everything outside bodies stay byte-identical. A
   rewritten body is `BT`, a prologue, its runs in reading order, ` ET`; a body left with no atom is
   `BT ET`.
   - Prologue: `0 Tw` when the body's entry `Tw` is not 0, `100 Tz` when its entry `Tz` is not 100 (B.0
     entry state; the source body reset them itself, the rewrite must too). Nothing leaks: the `Q` after
     `ET` restores the text state.
   - A run = maximal sequence of the body's atoms that are consecutive on one new line, share font, size and
     `Tc`, and are each `array_linked` to the one before. Inserted atoms are never array-linked: consecutive
     inserted atoms of one body and font form one run, with no kerns; the old atom after an insertion
     starts a new run.
   - **Origin of a run.** Default: `1 0 0 1 x y Tm` at the planned GLYPH origin of its first atom, and the
     array starts with that atom's string; kerns in front of the first glyph are not emitted (they are
     already in that origin). Verbatim case: a run that starts at its source show's first glyph AND whose
     planned first-glyph origin equals that glyph's source origin (0.001 pt; an insertion earlier on the
     line moves it, then the default applies) AND whose `d` (below) is 0 copies the operand bytes of
     the `Tm` that precedes its source show (admission: every show has its own) and the array from its
     start, leading kern included (text-matrix origin). Kerns after the last glyph of a run are never
     emitted (every run has its own `Tm`, so they position nothing). Gaps between runs (between-body
     gaps, autospacing, the space font, insertions) are carried by `Tm`; no error accumulates.
     `Tc` and `Tf` are written for the first run of a body and on every change.
   - **Inside a run** every pair is array-linked. `d` = share of the laid-out line (C.3) - `share_src(source line)` at
     a share pair, 0 elsewhere, and 0 everywhere on a kept line. `d` = 0 (`|d|` <= 1e-6 pt) for all pairs of the run (ragged
     lines, rigid moves): the array slice is copied byte-verbatim. (A wider threshold lets the source
     share drift from the C.3 share along a run and fail (g) 5.) Otherwise each share pair's kern slot is
     written as ONE number `sum(slot) - d x 1000 / size`; an empty slot counts as 0, and when the two
     glyphs share one string the string is split there (`<AAAA> k <BBBB>`); slots of all other
     pairs are copied verbatim. `Tz` is 100 at every show (admission), so no horizontal scale enters the
     formula (`glyph_boxes.py:367, 399`). (Probe P5: dropping or recomputing a kern that did not need to
     change moved glyphs 0.02-0.06 pt, hence copy where nothing changed.)
   - Number format for recomputed values: coordinates with 4 decimals, kerns with 2, trailing zeros trimmed
     (S0 probe confirms raster identity of a re-emitted unchanged paragraph and of a re-justified line in
     this format). The emitter rounds FIRST and then derives every atom's planned origin from the rounded
     operands as written, so check (a) compares like with like (a 2-decimal kern errs up to 7e-5 pt at
     14.04 pt, and the errors of one line add up along a run).
   - The label body is rewritten only by a translation (C.3 baselines, C.8, E).
6. Verify, on the preview scratch and again on the live page; a failure reverts the transaction (C.7).
   Identity always means the replay join of B.0, never a texttrace field alone. "Replayed" = predicted by
   B.0 from the EMITTED stream, read back after the apply.
   (a) **bijection**: for the rewritten bodies, the replayed glyphs and the planned atoms are in one-to-one
       correspondence in order (body, font resource, code bytes, size, `Tc`, origin within 0.001 pt), with
       no replayed glyph left over (an extra inkless glyph such as a doubled space fails here); then
       every replayed glyph joins exactly one trace glyph (gid, origin within `_GLYPH_MATCH_TOL`) and no
       trace glyph of those bodies is left over;
   (b) outside the rewritten bodies: stream bytes identical, and the multiset of joined glyphs (font xref,
       gid, origin, colour) identical;
   (c) raster zero-diff at 2x outside the band (band = union of the old and new line boxes of the rewritten
       bodies, grown by 1 px);
   (d) the planned atoms' Unicode in reading order equals the new text with atom-less mask positions
       removed, and each joined trace glyph reports that atom's Unicode;
   (e) every glyph in the band belongs to a body resource whose xref is one of the paragraph's original
       fonts or the recorded donor;
   (f) coarse, from replayed positions, for the laid-out lines of (g) 6: no line's last non-whitespace atom has its
       advance end (origin + natural advance) beyond the effective measure + 0.31 pt (the fit tolerance
       plus rounding); every line whose C.3 share is above 0 ends within 0.31 pt of it;
   (g) **independent of the plan's coordinates**, from replayed positions and SOURCE geometry only. The
       line partition is read from the REPLAY (which atoms share a baseline), never from the plan; the
       arithmetic is C.3's functions, CALLED here, not restated. The inputs of those calls are the
       source atoms and the C.1 mapping WITH its masks (`inferred_ws` and atom-less `join_sep` positions, hard breaks),
       in the order the replay confirms. A bug inside the shared functions is not caught by (g) 5/6;
       the independent checks are (f) and (i), the S3 tests against hand-computed expectations, and a
       test-only second implementation of C.3 compared with the product one on seeded random
       sequences (S3). (c) and (j) do not help here: (c) looks outside the band, (j) at planned
       positions.
       1. on LAID-OUT lines only: the first atom sits at the line's anchor (C.2: label x0, first-line
          body x0, the own start of the source line whose baseline it takes; effective geometry)
          within 0.01 pt. Kept lines are not held to an anchor: admission allows their starts to
          differ by up to 0.3 pt and (g) 4 holds them to their source origins;
       2. the label-to-first-body-atom displacement equals the source's;
       3. every line's baseline is an (effective) source baseline of its segment position, a `previous + pitch`
          continuation, or, after the re-broken segment, its source baseline + k x pitch for the one k of
          this edit;
       4. every atom of a KEPT line (C.3 scope: before the range start, converged, rigidly translated)
          has its (effective) source origin within 0.001 pt (the tolerance of (a); a recomputed `Tm` y is
          rounded), + (0, k x pitch) on a translated line;
       5. on LAID-OUT lines only: every adjacent pair of atoms (kept, inserted, joined across a former
          line break, next to a deleted or materialized mask position, hanging whitespace alike) has the
          C.3 gap within 0.01 pt (share at share pairs only). `ilead` and the line's share come from the C.3 functions applied to the
          SOURCE atoms, the C.1 mapping and the replayed line membership; nothing is derived from the
          replayed widths and nothing is taken from the plan;
       6. the range start is recomputed by the C.3 rule from the source lines and the C.1 mapping, and
          `break_lines` run from it on the replayed atom sequence (effective geometry) returns exactly
          the replayed line partition, up to and including the break before a converged line. This
          proves that every soft break of the range is legal and required (a plan that keeps an old
          break although text now fits, i.e. no pull-up, fails here, the break INTO the first edited
          line included when the range was extended) and that no line overflows;
   (h) per joined glyph: trace colour, opacity, render type and font size equal the source atom's; inserted
       atoms equal their body's. Line width is not compared (texttrace does not report the document pen;
       render mode 0 is an admission condition);
   (i) every planned glyph ink box (B.0) lies inside its body's effective clip (B.0, all enclosing scopes)
       and the CropBox, and meets no glyph ink of another paragraph, drawing, image or annotation;
   (j) glyph-identity mask (probe P4), PER GLYPH. Reference = the planned (font program bytes, gid, origin)
       drawn by the glyph-id renderer at 2x on the band's uniform background. Both rasters are binarised
       (pixel differs from the background or not); for each planned non-whitespace glyph the mismatching
       pixels inside its ink box grown by 1 px are counted; pass = at most `T` for every glyph, and the
       band outside all ink boxes holds no ink. `T` is fixed in S0 (maximum over every glyph of the
       fixtures and the reference file for a correct emission, + 1) and must stay below the smallest
       single-glyph mask of those glyphs, so a missing or clipped-away glyph always fails; S0 fails the
       design if that cannot hold. Measured controls on one line: correct 0, wrong gid 6017, a 0.3 pt
       move 9. Position is proven by (a) and (g), colour by (h). Known limit: tone values differ from the
       page renderer (max delta 40-42, cause not found), so (j) is never an exact-raster claim;
   (k) shift variant: every shifted glyph moved by exactly the growth, nothing else moved;
   (l) the marked-content operators of the stream are byte- and order-identical, every rewritten body lies
       in the same `BDC … EMC` and `q … Q` as before, and every surviving atom is still in its body. Known
       limit: the logical order in the structure tree (`/K`) is not re-proven; atoms keep their owners, so
       it is the order the source had;
   (m) every inserted atom sits in its planned owner body, which is neither a label nor a space-only body.
7. Transaction, tokens, tier id. Two facts rule this part, both measured:
   - **`xref_epoch` proves less than revision 3 assumed.** An equal epoch proves that surviving objects kept
     their numbers; it does NOT prove that an unreferenced object still exists. Save-over-open and the
     `garbage <= 1` round trip restore the epoch (`pdf_model.py:4962-4966, 5107-5114, 5945-5949`) while the
     reopened file has dropped every unreferenced object (probe P1; probe P7: the freed numbers stay as
     `null` slots, the table is not shortened, `update_object` works at them, new objects append).
   - **Copy-on-write orphans objects too.** Making an indirect `/Resources` or `/Font` direct leaves the old
     object unreferenced when no other page shares it; after a save the page bytes captured before the
     resource step hold a dead reference although the epoch is unchanged.
   Therefore nothing that outlives one call is replayed from saved object bytes or from an xref number,
   and there is NO epoch branch: undo and redo of a donor edit use one content-proved protocol in every
   situation. Saved bytes are used only as the rollback of the SAME call (no save can happen inside it).

   - `CommitTier` gains a member for Tier 2R. Success is `COMMITTED`, `allows_external_reflow=False`; font
     outcomes name each donor use and any `lang_mismatch`. Tier 2R joins `HIGH_FIDELITY_TIERS` and
     `fidelity_protected_pages`.
   - **Stream-only commits (no donor)** change one content stream and nothing else. They need no new
     record: `EditTextCommand` captures today's one-stream reversal (`build_reversal_patchset`, a whole-
     stream pair) and undo/redo/relocation run today's code with ONE change. `_relocate` returns `None`
     when the recorded xref layout is unchanged (`edit_commands.py:703`), but the layout tuple (`:656`)
     does not hold the `/Properties` targets whose numbers enter `page_fingerprint`
     (`marked_content.py:523`): a `garbage=4` merge of two identical `/Properties` objects fails the
     fingerprint with an equal layout, and a command whose page content is intact becomes STALE. The
     equal-layout early return is removed: after a fingerprint failure the content-proved relocation is
     always attempted, and the renumbering-invariant comparison that follows (`:726-735`) still refuses
     every change the invariant covers (`inspect.py:990-1004` lists what it does not). This applies to Tier 0/1 commands as well (same code).
   - **Donor commits** carry `last_commit_outcome.retypeset_record`. For such an outcome `execute` does NOT
     call `_capture_tier0_reversal` (`edit_commands.py:452-458`), `_tier0_*` stay `None`, and `undo` /
     `_redo` dispatch on the record BEFORE the `_tier0_forward_patchset` test (`:513-514`). The record
     logic lives in `model/text_commit/retypeset_replay.py` (Qt-free); the command only calls it.
   - **Resource step** (`model/text_commit/donor_resource.py`). Fresh resource name = `FD` + the lowest
     number unused in the page's effective font dictionary (same on scratch and live, the fingerprints
     being equal). `add_font_resource(doc, page, name, donor_xref)`: read the effective `/Resources`
     (the page's own direct dictionary, its indirect object, or the inherited one) and record the
     **source form** (`direct` / `indirect` / `inherited` for `/Resources`; `direct` / `indirect` /
     `absent` for its `/Font`); write the page object with a DIRECT `/Resources` whose entries are the
     effective dictionary's entries verbatim (nested references stay references) and whose `/Font` is a
     direct dictionary = the effective entries + the new key. The write is a byte-range edit of the page
     object's source text (key located with the object lexer, everything else verbatim) through
     `update_object`. No existing entry is repointed, no existing font object is mutated, another page
     sharing the old object is untouched.
     `remove_font_resource(doc, page, name, record)`: require that the key exists and that its target's
     donor digest is the record's; remove the key; `/Font` source `absent` -> remove the now empty
     `/Font`; `/Resources` source `inherited` -> require that the direct dictionary's canonical content
     (`_ContentWalker.value`) equals the inherited dictionary's, then remove the page's `/Resources` key
     (a direct copy would change the marked-content fold, `marked_content.py:113-126`, and the invariant,
     `inspect.py:1026-1030`, and make earlier relocatable commands of the page STALE); source `indirect`
     -> the direct copy stays (references are transparent to the invariant, `inspect.py:845-849`, and
     `page_fingerprint` reads resolved tables). The result is then REQUIRED to have the recorded
     no-donor invariant, so any case this reasoning missed is a rollback, not a silent difference.
   - **Donor digest** = sha256 of the reference-transparent canonical content of the donor font object graph
     (`_ContentWalker`; streams by decoded bytes, encoding keys ignored). **Ensure donor**
     (`ensure_donor(doc, record) -> xref`): the object at the recorded xref when its digest matches; else
     any Type0 font object of the document with that digest (in-document donors, and a system donor that
     a `garbage=4` save merged or renumbered); else, for a system donor, `embed_donor(doc, payload)`
     again, whose result must have the recorded digest; else STALE. `embed_donor` is the ONE function
     that creates the objects, at commit and at redo alike; the payload is plain data with no object
     number in it (font program bytes, base name, `/W` text, ToUnicode bytes, descriptor numbers), so
     there is no separate "re-create from saved object bytes" path to prove.
   - **States.** With the patched stream elided, a page has two invariants: `inv_absent` (no donor key) and
     `inv_present` (donor key present), both `renumber_invariant_page_fingerprint(elide_stream_xref=…)`.
     The stream has two byte states, S0 and S2. F0 = (`inv_absent`, S0), F1 = (`inv_present`, S0), F2 =
     (`inv_present`, S2). A state is proven by its invariant AND the exact stream bytes; the stream is
     found by its exact bytes among the page's contents, exactly one, not shared with another page (as
     `_relocate`, `edit_commands.py:710-725`). `page_fingerprint` (which hashes xref numbers) is never
     compared against a recorded value: after a state is proven, the patch set is keyed to the page's
     CURRENT `page_fingerprint` and applied through `apply_patchset`, whose splice still gates on the
     expected bytes and digest.
   - **Commit** (live document, inside `edit_text`): prove the token (below) -> capture the rollback (page
     object source text, stream storage) -> record `inv_absent` -> ensure donor (first time: in-document
     lookup or `embed_donor`) -> `add_font_resource` -> record `inv_present` -> apply the patch set ->
     verify (C.6) -> record. Any failure after the first write: restore the stream storage, then the page
     object text; require (`inv_absent`, S0); return `tier2r_commit_failed` with zero mutation. "Zero mutation" =
     every reachable object and the page's rendering restored; objects created by `embed_donor` stay
     unreferenced and are dropped by the next save (the same lifetime undo already gives a command's
     objects, `pdf_model.py:5933-5935`).
   - **Record**: S0/S2 patch pair (whole stream), `inv_absent`, `inv_present`, resource name, source form,
     donor kind, donor digest, last known donor xref (a hint only), the system-donor payload. No page
     object bytes, no epoch.
   - **Undo**: capture the rollback -> prove F2 -> apply the inverse patch -> `remove_font_resource` ->
     require (`inv_absent`, S0). **Redo**: capture the rollback -> prove F0 -> ensure donor -> require the
     name unused -> `add_font_resource` -> require `inv_present` -> apply the forward patch -> require
     (`inv_present`, S2); no re-verify, the result is content-identical to the verified commit. Any step
     that fails or cannot be proven: restore the stream storage and the page object text of THIS call,
     require the starting state, report STALE (`STALE_UNDO` / `STALE_PLAN`), the command stays on its
     stack as today. The X1 sequence (commit -> undo -> save over the open file -> redo) therefore
     re-embeds the donor; commit -> save -> undo removes the key by name and content. Around the
     protocol the command does today's bookkeeping unchanged: protection membership and the
     MaintenanceBook are restored and the page index is rebuilt (`edit_commands.py:859-861, 932-937`).
     The exact stream STORAGE of the commit is not restored on this path (as after a relocation,
     `:816-821`): the decoded content is exact and the next save re-serializes the stream.
   - **Structure closure digest**: sha256 over, for every MCID of the page's ParentTree entry in order, the
     MCID and its owner chain up to the root as a list of (resolved structure type, `/Lang`, presence of
     `/ActualText` / `/Alt` / `/E`, index in the parent's `/K`). It contains no object number, keeps the
     MCID -> owner mapping and the `/K` order, and is not the invariant's reference substitution
     (`inspect.py:893-906`). Folded into the token and re-checked at Apply; NOT re-checked at undo/redo
     (Tier 2R never writes the tree, and the stream gate is exact).
   - **Token** = `t2r:<variant>:<digest>`; preimage: page fingerprint, closure digest, every splice (offset,
     digest of the expected bytes, replacement bytes), resource name, donor identity, new text,
     `edit_caret`, `new_rect`, `style_overrides`, variant (`fit` / `shift`). Donor identity: the donor digest for an
     in-document donor; (face file digest, face index, sorted gid tuple, embed format version) for a
     system donor, so it does not depend on emitted subset bytes (probe P8: two fontTools subsets of the
     same face and glyphs differ in `head`; with `recalcTimestamp=False` they are byte-equal, and
     `embed_donor` input is built that way).
   - **Preview transport.** The Controller opens a session when `derive_tier0_preview_target` OR the new
     `derive_paragraph_preview_target` succeeds (`pdf_controller.py:5501-5575`).
     `PlanPreviewCoordinator.request` (`text_commit_coordinator.py:173`) and `PlanPreviewRequest` carry
     BOTH targets (either may be absent) plus `edit_caret`; the worker runs C.0's order: Tier 2R when a
     paragraph target is present, then Tier 0/1 when a Tier 0 target is present and Tier 2R refused
     admission. A paragraph that binds is planned by Tier 2R from its first keystroke; the Tier 0 target
     serves only a paragraph Tier 2R refuses, and such a session does not wrap (today's behaviour). `PlanPreviewResult` keeps ONE `plan_token` and ONE
     image (the `fit` variant, or the Tier 0/1 candidate) and gains `kind` and `growth_offer`
     (`GrowthOffer(shift_token: str | None)`, set exactly when `reject_reason=REFLOW_DOES_NOT_FIT`).
     `prepared` stays `None` for Tier 2R: the scratch plan is never transferred to the live engine cache
     (`engine.py:116-131, 284` holds Tier 0/1 candidates only). When both tiers refuse, the reported
     reason is Tier 0's, as today. The shift variant has a token but no inline image; its result is seen
     after Apply and can be undone.
   - **Scratch rendering.** Each render: ensure donor on the scratch (one graph per donor identity, reused
     across keystrokes), resource step, patch, render, then restore the page object text and the stream
     storage (same handle, no save in between, so the saved text is valid). Names and digests do not
     drift between keystrokes.
   - **Apply.** The View enables Apply when `current_plan_token()` OR a generation-bound
     `current_growth_offer()` exists (today only the token, `view/text_editing.py:3046-3047`). With an offer
     the Controller opens the C.4 dialog; nothing is committed without a token. `edit_text` dispatches on
     the token prefix BEFORE `_attempt_tiered_commit` (a paragraph token is terminal `PREVIEW_STALE` there
     today): for `t2r:` it binds and plans AGAIN on the live document from the request (new text,
     `edit_caret`, `new_rect`, variant, the paragraph resolved from the fresh index), recomputes the token
     and requires equality; a mismatch, or a `tier2r:` refusal of this live re-plan, is terminal `PREVIEW_STALE`; a failure after
     the patch set exists is terminal `tier2r_commit_failed` (rolled back). Neither falls through to another tier or to the consented rebuild.
   - **Tokenless callers** (internal): Tier 2R runs first when the paragraph binds (C.0), before
     `_attempt_tiered_commit`, hence before the `settings.strict` return
     (`pdf_text_edit.py:5054-5061`) and before any consent. Inline Apply with no token keeps returning
     `PREVIEW_PENDING`.
   - **Caches.** Page pass: per document object, plain data (B.0). `font_discovery`: one process-wide cache
     behind a lock (the preview worker and the GUI thread both read it); candidate order is deterministic
     (sorted by file digest), so scratch and live choose the same face.
8. Box drag and resize while editing (owner 2026-11-13). For a bound paragraph the editor box is the
   paragraph frame: a right-edge change sets the measure; a left-edge change moves the label, first-line
   and continuation x0 by the same amount; a move translates every line including the label; height
   follows the line count. The rect travels as `new_rect` and is part of the token; C.4 and C.6 (i) apply
   to the new frame, and the anchors of C.6 (g) are the source anchors moved by the same amounts. A drag with unchanged text is a
   Tier 2R edit of a bound paragraph (C.3 frame change). Unbound paragraphs keep today's
   dragged-rebuild behaviour (S17-DRAG-GUARD).

### D. Glyph supply (`model/text_commit/same_face.py`; discovery in `model/font_discovery.py`)

Owner decision 2026-11-14: system-font donors are part of v1 (a subset font lacks most characters a user
types). Designer's order: the donor TRANSACTION (C.7) is built and tested first with the in-document donor
(S6a), the system donor follows (S6b), and activation (S7) waits for both.

Donor candidates for an inserted character: (1) in-document embedded TrueType programs, ordered by
(FontFile content digest, lowest font xref), so the pick among same-named copies is deterministic (the
reference page lists 11); (2) system faces found by `font_discovery` (system and per-user font
directories, name-table family match, `.ttc` members by index), ordered by file digest.
Proof, identical for both (promoted from `scripts/audit_same_face.py`): every non-empty glyph program of
the paragraph font's subset is byte-identical in the candidate with equal `hmtx` advance; `fpgm`, `prep`,
`cvt ` and the hinting-relevant `maxp` fields are equal; the subset holds at least 20 proven glyphs in the
inserted character's script class; the candidate's cmap maps the character to a glyph (non-empty, except
whitespace); `fsType` is 0x0000 or 0x0008, and 0x0100 is clear when a subset would be embedded. Anything
else: no donor.
Use:
- In-document donor: one new font key (C.7 resource step) pointing at the existing Type0 object. Required:
  Identity-H, CID = GID (no non-identity `CIDToGIDMap`), a `/W` or `/DW` width for the CID equal to the
  scaled `hmtx` advance, a ToUnicode entry for the CID whose reverse mapping is unique (probe P6: object
  3966 meets all of this for the ten inserted characters). No object is created. If the donor object is
  later removed from the document, redo is STALE.
- System donor: `embed_donor` (C.7). Input: a fontTools subset of the face holding exactly the glyphs this
  edit inserts plus `.notdef`, GIDs retained, hinting tables kept, `recalcTimestamp=False` (probe P8).
  Output: a NEW Type0 / CIDFontType2 graph (FontFile2, FontDescriptor, CIDFont with `/W` for the used
  glyphs and `/DW`, Identity-H, CID = GID, ToUnicode for the used glyphs). Nothing existing is mutated.
  The donor becomes a font of the paragraph: a later edit finds its glyphs under "other fonts of the
  paragraph" (C.1) and embeds a further donor only for further glyphs.
- No donor: `tier2r:glyph_unavailable`; the chain continues.
S6 probes before building: a donor-subset glyph and the full-face glyph are raster-identical at 2x;
`embed_donor` run twice on one document gives two graphs with equal donor digests, and after `save` +
reopen the digest is unchanged.

### E. Line spacing

Model API `set_paragraph_line_pitch(page_num, anchor_points, pitch_pt)`; the paragraphs are resolved from
the fresh index (A.5), consecutive in one column. No text changes. Same unit and admission as C.5: every
body with an atom on a moved line is rewritten whole, each run's `Tm` y changed, `Tc`/`Tf` and array bytes
copied verbatim (the C.5 prologue and run-origin rules apply). The first line of the first paragraph is
anchored; every baseline step inside the selection equal to the old pitch becomes the new pitch, larger
steps keep their extra. Content outside the selection never moves. A result that passes the floor refuses
`LINE_PITCH_DOES_NOT_FIT` (plain zh-TW message, no dialog). Verify: C.6 (a)(b)(c)(h)(i)(l) plus "every
moved glyph moved only vertically by its line's delta". Command `SetParagraphLinePitchCommand`: a
stream-only commit, so it shares the one-stream reversal, undo/redo and relocation code of
`EditTextCommand` (moved to a helper both commands use).

Scope query `consecutive_same_level_paragraphs(page_num, point)` -> anchor points of the run of consecutive
paragraphs in the same column with the same pitch (5 %), continuation x0 (1 pt) and size. View: a 「行距」
control (1x / 1.15x / 1.5x / 2x / custom; multiples of the font's natural line height, hhea (ascender -
descender + lineGap) / upm from the embedded or donor program, 1.2 em when unreadable) and a checkbox
「套用到相連的同層段落」. `ParagraphLayoutInfo` is a DTO in `model/edit_requests.py`, imported only by
`view/text_editing.py` (allowlisted); `view/pdf_view.py` receives plain values through the Controller.

## 5. Layers and modules

| Module (layer) | Change |
|---|---|
| `model/text_commit/page_pass.py` (Model, new) | B.0: scope/body segmentation, clip chain, entry text state, glyph prediction, trace join, ink boxes, owner lookup, structure closure. |
| `model/text_commit/replay.py`, `glyph_boxes.py`, `simple_font_programs.py` | `ShowOp.q_open_offset`; `predict_glyphs` for simple fonts through `route_gids`; `_GLYPH_MATCH_TOL` home. |
| `model/paragraph_grouping.py` (Model, new) | A.1-A.5. |
| `model/text_block_parsing.py`, `model/text_block.py`, `model/page_content_text.py` | call the pass; A.6 text, `inferred_ws`, `join_sep`, `constituent_block_ids`. |
| `model/text_reflow.py` (Model, new, no mutation) | layout detection + breaker (re-break range, baselines). |
| `model/text_commit/paragraph_source.py` (new) | binder, atoms, lead-ins, shares, admission (B.1). |
| `model/text_commit/marked_content.py` | `admit_tier2r_wrappers`, `/E` refusal. |
| `model/text_commit/retypeset.py` (new) | C.1, C.4-C.6 plan, emit, verify; E planning; token. |
| `model/text_commit/donor_resource.py` (new) | `add_font_resource`, `remove_font_resource`, `embed_donor`, `ensure_donor`, donor digest. |
| `model/text_commit/retypeset_replay.py` (new) | donor record, state proof, undo/redo protocol with same-call rollback. |
| `model/text_commit/same_face.py`, `model/font_discovery.py` (new) | D: same-face proof; locked discovery cache. |
| `model/text_commit/preview.py`, `engine.py`, `plan.py`, `dto.py`, `verify.py` | both targets in the request, Tier 2R first, `kind`, `growth_offer`; tier member and `tier2r:*` reasons; verify (a)-(m). |
| `model/pdf_text_edit.py`, `model/pdf_model.py`, `model/edit_commands.py` | `t2r:` token dispatch with live re-plan, tokenless Tier 2R before `_attempt_tiered_commit`, union target; `paragraph_at`, line-pitch delegate + query; record-first undo/redo dispatch; shared one-stream reversal helper. |
| `model/edit_requests.py`, `model/text_edit_refusal.py` | `edit_caret`, `ParagraphBindTarget`, `ParagraphLayoutInfo`, `paragraph_anchor`; `REFLOW_DOES_NOT_FIT`, `LINE_PITCH_DOES_NOT_FIT`. |
| `controller/text_commit_coordinator.py`, `controller/pdf_controller.py`, `controller/text_edit_refusals.py` | request with both targets; growth offer cached per generation; dialog; re-select by anchor; line-pitch slot (wired in `activate()`); zh-TW sentences. |
| `view/text_editing.py`, `view/pdf_view.py`, `view/message_boxes.py` | caret offset in the edit signal; Apply enabled by token or growth offer; 行距 control + checkbox; `ask_reflow_growth_choice`; box resize feeds the preview. |
| docs | ARCHITECTURE 10.x, PITFALLS entries + index, FEATURES, TODOS. |

No ToolManager change. Nothing crosses View -> Model.

## 6. Slices (red-light first). Everything is internal (flag off) until S7.

Test rule. From S5 on, every refusal or negative test first shows the edit COMMITTING through Tier 2R on
the same fixture (in the same test or a module-level positive control), then sets ONE precondition and
asserts the chain entry `tier2r:<reason>` plus a byte-identical document. Before S5 no commit path exists,
so S1-S4 tests assert the RESULT of the page pass, the grouping, the breaker or the binder on a fixture
that also holds the positive case. A test that can pass before the stage exists is invalid.

- **S0 fixtures and probes (no product change).** Fixture builder (fontTools `FontBuilder` synthetic faces:
  a full face and subsets cut from it, no font file committed) writing tagged one-page PDFs of the
  reference shape; the builder's test asserts MuPDF yields the two-block split with item 2 fused. Probes,
  recorded in the Log, in this order: (1) hand-made REAL reflows of item 1 with body-unit emission, each
  re-indexed with a prototype of A and checked with a prototype of the B.1 admission predicates (every
  body rewritable, stream order, text check): (i) an insertion that wraps a word across a body boundary,
  (ii) growth by one line, (iii) a deletion that pulls a word up and one that removes a line (later lines
  translated), (iv) a donor run, (v) a line-pitch change applied to the output of (i). Expected each
  time: item 1 is one paragraph, item 2 its own, and the admission predicates hold again. If this fails,
  revise A before S1; (2) the C.5 number format: re-emitting an unchanged paragraph is raster- and
  trace-identical, and item 1 line 1 (it ends AT the measure, so its C.3 share is its source share) laid out again
  with 15+ recomputed kerns passes (a) and (g) 5 and is raster-identical to the source; (3) threshold `T` of C.6 (j) per glyph over all fixture and reference glyphs, and the
  smallest single-glyph mask; (4) does a clipped glyph still appear in texttrace/extraction; (5)
  CJK-Latin autospacing gap sizes; (6) cost of the ink-box renderer for one paragraph; (7) a prototype of C.3 `break_lines` on the
  UNCHANGED paragraphs of the reference file and the fixtures returns their own lines (the producer's
  breaks are greedy under C.3 within its 0.3 pt tolerance, so a typo fix does not re-flow the
  paragraph); if not, revise C.3 before S3.
- **S1 page pass (B.0).** Red tests: every show of the reference-shape fixture joins one trace glyph with
  the right font xref and MCID; body ranges, entry text state, clip chain; `re W* n` admitted; a
  non-rectangular clip or a `cm` in an ENCLOSING scope -> `unproven_outer_state`; inherited `Tw` not
  reset in the body -> not rewritable, reset by `0 Tw` in the body -> rewritable; overprinted duplicate ->
  ambiguous join; simple-font routes that disagree -> unbound; owner lookup and closure digest (equal
  after a renumbering save, different after a `/K` reorder). `scripts/census_page_shapes.py`: B.0
  evidence only (share of bodies that are rewritable, and why not).
- **S2 grouping + text (A), flag on in tests.** Red tests: item 1 is ONE 3-line paragraph and item 2 its
  own; the post-edit shapes of S0 probe 1 regroup; the negative and positive controls of A; text without
  synthetic spaces, CJK lines joined with nothing, hyphen join unchanged, no join space after a line that
  ends in whitespace, `inferred_ws` and `join_sep` offsets for `[(Hello) -500 (world)]TJ`; `_p0` rule;
  union target. Flag pair: with the flag off the fixture's index equals a recorded pre-change dump, and
  the SAME test asserts that with the flag on it differs in exactly the listed paragraphs.
- **S3 breaker.** Font-agnostic tests inherited from `paragraph-reflow.md` 7.1, plus kinsoku, hanging
  indent, fixed label gap, shares, **pull-up** (a shortened line takes the next word; a segment that
  loses a line translates the paragraph's later lines up by one pitch; a hard break is not crossed),
  growth translates later lines of the paragraph down, convergence needs same baseline and x, measure
  change disables convergence, one-line paragraph pitch. The C.3 definitions, each against a hand-computed
  expectation: `the quick ` over `brown` (the hanging space is not counted; the break stays when
  `brown` does not fit and goes when it does, the space then counted); an atom-less `join_sep`
  materialized by a pull-up; a first atom with a source lead-in (not counted, share not negative); a
  line with no opportunity (share 0); a ragged paragraph never justified; the
  last line of a justified paragraph never stretched; the 0.5 em cap; no break before `。` or after
  `（` or inside `2026年11月14日`'s digits; a unit wider than the measure ->
  `tier2r:unbreakable_overflow`; an unchanged paragraph returns its own lines. Revision 8: the range
  start (a deleted first glyph that leaves `，` and a deleted long first word both start one line
  earlier; an edit inside the line does not); a narrowed measure re-breaks every segment with
  unchanged text, a pure move re-breaks nothing; a whitespace-only unit never starts a line;
  justification evidence (ragged lines with equal ends and unwidened gaps: not justified, an edited
  line is not stretched; a two-line paragraph with widened gaps: justified; a justified line with no
  opportunity: `share_src` 0); the measure is the largest line end when the widest line is edited;
  the test-only reference implementation of C.3 agrees with `break_lines` and the shares on 500
  seeded random sequences. Revision 9: word spaces made by `TJ` kerns (`inferred_ws`): the paragraph
  is ragged and a typo fix that pulls a word up keeps every word gap at its source size; ragged Latin
  tracked with `Tc` 0.5 and CJK on a grid whose last line has no CJK/CJK pair: ragged; lines 1-2 at
  `Tc` 1 and the last line at `Tc` 0 with equal ends: ragged (uniform tracking); a justified paragraph
  with one compressed line: that line's `share_src` is 0 and it still fits when laid out again; a
  line whose whole text is deleted re-lays the line before it as a last line; a horizontal move
  re-breaks nothing; a laid-out line keeps the start of the source line whose baseline it takes.
- **S4 binder (B.1) + census.** Red tests: atoms, lead-ins and shares reproduce every source glyph
  position; the label gap and the space-font gap survive; a whitespace atom with an empty glyph binds;
  one refusal test per admission rule (body with a second text object in its scope, operator outside the
  alphabet, two shows after one `Tm`, scaled `Tm`, non-identity CTM, two streams, shared stream, Form XObject, clip not one
  rectangle, `gs` in scope, effective `Tw`, rise, `Tz`, `Tr 2`, rotated page, RTL, centred / right-aligned (also `[30,70] [0,100] [0,100]` and its right twin, and a centred block of
  hard-break lines) / two-line shape without a label or column evidence (`tier2r:alignment`; a
  centred ONE-line paragraph binds, Q3; a two-line paragraph whose continuation start is evidenced by
  a 3-line neighbour binds; a single widest line whose final `，` alone protrudes ->
  `tier2r:hanging_punctuation`, while a widest line that stays widest without its `，` binds), annotation in band,
  image under the band, ActualText, `/E`, `/Link` owner, stream order), each beside a paragraph of the
  same fixture that binds. `scripts/census_paragraph_shapes.py`: per corpus paragraph, the first B.1
  admission rule it fails, and how many block paragraphs A.2/A.3 change.
- **S5 Tier 2R core (C.0-C.3, C.5-C.7 stream-only), no donor, no growth.** Red tests: insertion with glyphs
  the paragraph holds -> preview token -> token-bound `edit_text` ends `COMMITTED` with the Tier 2R tier;
  deletion with pull-up, typo fix and equal-length replacement also commit through Tier 2R; every
  surviving atom keeps (font xref, gid, MCID); checks (f) and (g) each with a wrong-output control (a
  ragged line translated 2 pt, a doubled space, a glyph under an enclosing clip, a run at a wrong size
  must each FAIL verify and roll back; so must a deletion on a JUSTIFIED line whose plan keeps the old breaks and re-justifies, and an
  inserted run placed 2 pt to the right); a date such as `2026年11月14日` at a break and a narrowed
  frame both commit (no false failure of (g) 6); an
  insertion before a later show of the same ragged line commits (that show's `Tm` is recomputed); a
  mid-line edit does not converge on its own line; a request with a colour override is refused
  `tier2r:restyle_requested` and a token issued without it is stale; typed space and a join space that lands mid-line are real space
  atoms; a body with inherited `Tw` reset in the body is rewritten with the prologue; kern cases (CJK
  pair inside one string re-justified, leading kern not applied twice); outside raster/byte identical;
  **edit -> re-index -> second edit of the same paragraph**; undo, redo, save, reopen; undo after
  save-over-open and after a `garbage=4` serialization (today's relocation); a forced verify failure
  after apply restores byte-identical streams; text typed right after `1.` lands in the body, not the
  label; CJK typed after a Latin span; repeated text + `edit_caret`; a red word stays red (asserted
  against a plan that would emit it black); undo of an earlier Tier 0 edit on the same page; token
  mismatch at Apply is terminal `PREVIEW_STALE`; a forced verify failure on the tokenless path is terminal
  `tier2r_commit_failed` and never reaches the consented rebuild; a character no font of the paragraph
  holds -> `tier2r:glyph_unavailable` and the chain CONTINUES to Tier 0/1; an edit on line 3 of a
  paragraph whose line 1 has compressed (negative) producer gaps commits and leaves line 1
  byte-identical (kept line, (g) 4), while a plan that re-spaces line 1 fails verify; an exception
  injected BEFORE the patch set is `tier2r:internal_error` and the chain continues, one injected after
  it is `tier2r_commit_failed`, both with a byte-identical document; a paragraph whose kept
  continuation line starts 0.2 pt off the others commits (no anchor check on kept lines); inserting or deleting a newline -> `tier2r:hard_break_edit`.
- **S6a donor transaction + in-document donor (C.7, D).** Red tests: in-document donor used, no font
  object added; forced verify failure -> (`inv_absent`, S0) and page object text restored; inherited
  `/Resources`: direct during F2, removed again by undo, the other page's fingerprint and rendering
  unchanged throughout, an earlier Tier 0 command of the page still undoes afterwards; indirect
  unshared `/Resources`: commit -> save over the open file -> undo succeeds (no dead reference); the
  command holds no one-stream reversal and redo does not go through `_redo_tier0`; undo/redo failure
  injected at each step restores the starting state and reports STALE; commit -> `garbage=4`
  serialization -> undo (key removed by name; STALE when the target's digest differs); **donor edit ->
  re-index -> second edit**; Tier 0 command A, donor command B, undo B, a `garbage=4` serialization that
  merges two identical `/Properties` objects, undo A succeeds (fixture: the duplicates hold the HIGHEST
  object numbers, and the test asserts the layout tuple is equal before undo A; otherwise the
  compaction renumbers and today's code already relocates). The created-object cases are covered
  here with a test donor injected through the discovery seam, so S6b adds discovery and subsetting only:
  **commit -> undo -> save over the open file -> redo** re-embeds and ends at (`inv_present`, S2);
  commit -> undo -> `garbage=4` serialization -> redo; redo when the recorded xref now holds a foreign
  object; twenty preview renders leave one donor graph on the scratch and the token commits.
- **S6b system donor (D).** Probes first (D). Red tests with an injected font directory: the same-face
  proof accepts the face and the edit commits; candidates differing in one glyph program, in `prep`, in
  `fsType`, lacking the glyph, with a non-unique reverse mapping, or proven only on Latin glyphs for a
  CJK character are rejected with `tier2r:glyph_unavailable` (positive control: the unmodified candidate
  commits); a second edit reuses the embedded donor for a glyph it holds; the discovery cache is read
  from two threads; scratch and live pick the same face (token equality).
- **S7 UI + growth + box (C.4, C.8), activation.** Trace UI -> Controller -> prepare -> preview -> commit.
  Model red tests: growth into free space; no room -> `REFLOW_DOES_NOT_FIT` with and without a shift token
  (image below, rule between paragraphs, link annotation in the shifted band -> no shift token), and the
  tokenless path does not reach the consented rebuild; `tier2r:clip_too_tight` continues the chain; growth past the CropBox bottom is `REFLOW_DOES_NOT_FIT`;
  a right-edge drag with unchanged text re-wraps through Tier 2R; the shift token commits and moves
  exactly the following paragraphs; right-edge resize re-wraps, left-edge resize moves label and both
  indents, move translates the label. Controller/View tests: session opens for a paragraph with no Tier 0
  target; a bound one-line paragraph gets a `t2r:` token on its first keystroke and wraps when it overflows; a
  paragraph refused `tier2r:alignment` gets the Tier 0 token; the rebuild is not offered for
  `reflow_does_not_fit` and `tier2r_commit_failed` and is offered after a `tier2r:` refusal that Tier
  0/1 refuse too; its consent sentence names the font and the default button is No; Apply is enabled by a growth offer and disabled when the generation is stale; three buttons,
  default/Esc = back to editing, b and c make no model call (asserted on a spy that the positive path
  does call); re-selection by anchor after commit. Then `paragraph_grouping` on and Tier 2R reachable from
  the inline editor; acceptance on the reference file (section 7).
- **S8 line spacing (E).** Model + command red tests (1.25x -> 1.15x on items 1+2, pitch 21.0 -> 19.36:
  item 2 moves up 3 x 1.64 pt, headings identical, arrays and MCIDs byte-identical; **line pitch after a
  Tier 2R edit of the same paragraph** and after a donor edit; growing into the floor -> `LINE_PITCH_DOES_NOT_FIT`; scope query
  boundaries), then Controller and View.
- **S9 (not designed here)**: FIRST after v1 (owner 2026-11-14): a substitute-font donor for inserted
  characters only when no same-face donor exists (needs its own proof and outcome wording: the new
  characters are declared as a different face, everything else is still verified unchanged). Then:
  multi-paragraph text frame and selection; indent/alignment editing;
  centred and right-aligned paragraphs; right-to-left paragraphs; rotated pages, non-identity CTM or scaled `Tm`, `Td`-chained and
  one-`TJ`-per-line shapes, quote operators, multi-stream pages, non-uniform backgrounds; pulling LATER
  paragraphs up after a shortening edit (the owner decided they stay).

## 7. Acceptance (per `.agents/skills/pdf-text-fidelity`, on the reference file, `local_only`)

Through the normal UI: paragraph mode, click item 1, type `（包含測試點位範本）` after `文件範本`, preview,
Apply, undo, redo, save, reopen. Pass = item 1 is one editor; the text re-wraps over three lines with the
hanging indent; every unedited character keeps its font object, glyph id and MCID; the five new ideographs
come from a proven same-face donor; justified lines end at 539.2 +/- 0.3; item 2 and all other page content
are raster-identical at 2x; text extraction returns the new sentence without synthetic spaces; the same
after save + reopen. Then, in this order on the edited file: line spacing 1.25x -> 1.15x on items 1+2 with
the same checks; a second text edit of item 1 (a typo fix, which must commit through Tier 2R); a deletion
in line 1 of item 1 long enough to pull text up (later lines of item 1 move up, item 2 and everything
below stay raster-identical); undo of all four after a save; then redo of all four (the donor edit is
re-embedded or found by content). Report per phase as pass / fail / not_run / blocked with the evidence
file.

## 8. Risks and dead ends

- v1 admission is narrow by design (the reference shape). The S1 census decides which S9 shapes come next.
- Grouping is a heuristic over every document; it stays behind `paragraph_grouping` until S7 and the
  negative controls are the guard. A wrong merge never mutates anything by itself; Tier 2R re-proves the
  text.
- Re-edit depends on MuPDF's block segmentation of OUR output (probe P5: ids shift, blocks fuse or split).
  The design never keeps ids and relies on A to regroup; S0 probe 1 tests this on a real reflow before
  anything is built.
- Known limits, stated in A-C: an emptied body (`BT ET`) leaves an empty marked-content sequence; an
  inserted character may sit in a span with another `/Lang` and gets no autospacing of its own; the
  structure tree's logical order is not re-proven; check (j) proves glyph identity, not tone; right-to-left
  paragraphs are neither regrouped nor bound; on an untagged page with no column measure nothing merges; a
  lone marker line after a full line of a non-list paragraph stays fused; after undo of a donor edit an
  indirect `/Resources` may remain as an equal direct copy; a shortening edit leaves empty space below
  the paragraph.
- Undo and redo of a donor edit never trust an object number or saved object bytes: the state is proven by
  content, the donor is found by digest or re-embedded, and any step that cannot be proven is STALE with
  the starting state restored, never a guess. Each system-donor edit adds one small subset font; unused
  ones are dropped by the next save.
- Dead end: an `xref_epoch` branch for the donor resource (revision 3). An equal epoch proves that
  surviving objects kept their numbers, not that an unreferenced object still exists (probes P1, P7), and
  copy-on-write of `/Resources` can itself orphan the old object.
- Dead end: Tier 0 before Tier 2R for a bound paragraph: one gesture would reflow or not depending on
  whether the edit stays inside one show.
- Dead end: per-show splices with "last show of its `BT`" admission (revision 2): the output of an edit
  was no longer admissible, so a second edit or a line-spacing change after an edit refused.
- Dead end: restoring saved page-object bytes after a renumbering (dead references).
- DFKai-SB may be a hinting-dependent ("tricky") face; this is why D compares hinting tables and S6 opens
  with a raster probe.
- The in-document donor of the reference file is an accident of its Form XObjects; the system donor is
  the general path and must not be skipped.
- Dead end: gathering the re-typeset text into one host show (revision 1): it moves glyphs between
  structure elements and `q` scopes and needs full paint-state reproduction.
- Dead end: `insert_htmlbox` reflow (cannot justify one line, cannot keep the font).
- Dead end: mutating an existing font object on a live handle (ARCHITECTURE 10.1.3).

## 9. Owner answers (2026-11-13)

- **OD-1 slice order.** Original-font reflow first; the substitute-font reflow is not scheduled.
- **OD-2 a paragraph that needs more lines.** Free space below: grow down. No free space: the user chooses
  a. shift the paragraphs below down, b. back to editing, c. cancel the edit (C.4). Enlarging the box is
  not a dialog option: the box can be dragged or resized at any time while editing (C.8).
- **OD-3 line-spacing scope.** The edited paragraph, with 「套用到相連的同層段落」 (E).

Confirmed by the owner on 2026-11-14: option a is offered only when the band that would move contains
nothing but bindable text; with an image, a rule, a link or a highlight in that band the dialog shows only
b and c.

Q2 scope (2026-11-14, the owner was told and did not object): Tier 2R handles every edit of a paragraph it
binds, including deletions, typo fixes and equal-length replacements.

Owner decisions 2026-11-14:
1. System-font donors are part of v1 (missing glyphs are otherwise common); the build order is the
   designer's (section 6: S6a in-document donor and transaction, S6b system donor, both before S7).
2. Shortening a line pulls up the later lines of the SAME paragraph; later paragraphs stay in place. This
   replaces the inherited Q2 no-pull-up rule (C.3).
3. The probe scripts in `plans/paragraph-grouping-reflow-probes/` may be committed.
4. "Which tier commits is not the point; the font must not jump." A font change is never an automatic
   fallback (C.0).
5. Substitute font for inserted characters only: when no same-face donor exists (not in the document, not
   installed), only the newly typed characters use a substitute font; existing text keeps its font.
   Scheduled AFTER v1 (S9). Until then v1 refuses `tier2r:glyph_unavailable` and the chain of C.0 applies.

## 10. Review round 1 -> revision 2 (R = deep-reasoner finding, X = Codex finding)

| Finding | Resolution |
|---|---|
| R1, X1 MCID wrappers refused by `admit_show_wrappers` | B: `admit_tier2r_wrappers`, structure-owner refusals, splice rule. |
| R2, X15 token-bound Apply dead-ends in `PREVIEW_STALE`; shift retry has no token | C.7 token dispatch before `_attempt_tiered_commit`; C.4 shift variant has its own token; S4 red test. |
| R3, X2, X9 undo/redo, donor resources, shared `/Resources`, repointing | C.7 transaction record, copy-on-write, fresh name, never repoint; one stream in v1; S4/S5 tests. |
| R4, X3, X4 paint/clip not reproduced, in-band errors pass verify | C.5 in-place emission keeps each show's own scope; B replay evidence + v1 admission; C.6 (h)(i)(j). |
| X5 structure ownership lost by consolidation | C.5: atoms never change show; C.6 (l). |
| X6, R14 `[]` for `Tj`, quote operators, advance-positioned successors | B: `TJ`/`Tj` only, last show of its `BT`; whole operand..operator range replaced by `TJ`. |
| R5, X12 synthetic separators, `_compose_paragraph_text`, wrong "fix" claim, invalid red test | A.7 `space_before`, line-join rule, mask; C.1 alignment, `autojunk=False`; section 1 corrected; S1 asserts text. |
| R6 binder is new, order inverted | B scoped as a new binder (S3); A.4 lookup lazy; census needs no binder. |
| R7, X12 A.5 consumers wrong | A.5 rewritten to the real sites; `constituent_block_ids`; `_p0` rule. |
| R8, X11 grouping counterexamples | A.1 measure, A.2 a/b/c, A.3 vetoes, extended markers, negative controls. |
| R9, X7, X8 floor ignores non-text, shift leaves attachments, rotation | C.4 floor and shift-variant conditions; B refuses `/Rotate` and annotations in band; C.8 label moves. |
| R10, R11, X10 same-face proof, advance source, ToUnicode, `fsType`, discovery, fixture font | D rewritten; `font_discovery`; S0 synthetic faces; S5 probe. |
| R12 `glue_after` changes unedited glyphs | B glue definition; C.6 (g). |
| X13 convergence without baseline | C.3. |
| R13, X15 slices not independently shippable, missing red tests | section 6: activation at S6, merge flag, tests listed per slice. |
| R15, X14 line spacing: relative positioning, dialog, scope query, `replay.py` in table | E rewritten (prefix `Tm`, own refusal, scope query + checkbox); S8 for `Td` chains. |
| R16 `_right_wall` in index, `CommitTier`, DTO import, antialias margin | A.1 measure; C.7; E; C.6 (c). |

## 11. Review round 2 -> revision 3 (groups of `paragraph-grouping-reflow-review-r2.md`; P = probe)

| Group | Resolution in revision 3 |
|---|---|
| 1 emission unit, re-edit, scaled `Tm` | Section 4 terms: rewritable body is the admission and splice unit, any number of shows; identity `Tm`/CTM only; C.5; E on the same unit; S5 "edit -> re-index -> second edit", S8 "line pitch after an edit". P5 (body rewrite twice identical). |
| 2 donor transaction | C.7: resource step as one page-object rewrite to a direct dictionary; forward order with F0/F1/F2; record on `last_commit_outcome`; same-epoch undo/redo by bytes; other epoch by name + content digest with the existing stream relocation; zero mutation defined; S6 tests. P1 (`garbage>=2` renumbers the live handle; orphans live until a save). |
| 3 preview/token pipeline | C.7 preview and token preimage (content digest, no xref); scratch reverts both parts, one donor graph per digest; session for paragraphs without a Tier 0 target; request `kind`; `PreparedRetypeset`; token tuple; dialog from the preview result (C.4); binder takes a document + DTO (B); hook before `strict`. |
| 4 replay evidence for colour and clip | B.0: `ShowOp.q_open_offset` only, scope re-lexed without coalescing; `re W n` and `re W* n`; `unproven_outer_state`; C.4 `clip_too_tight` before the token. |
| 5 identity and verification | B.0 trace join (name + gid + origin; xref and MCID from replay; ambiguous join refuses); C.6 rewritten: (f) overflow rule, (g) per line pair, (h) without line width, (i) ink boxes, (j) mask metric with threshold and stated limit, (l) + reading-order limit, (m); reverse-unique mapping (C.1, D); structure closure digest (C.7); `/E` refused; `predict_glyphs` extension; `_GLYPH_MATCH_TOL` moved. P3, P4, P6. |
| 6 glue | B.1 geometric glue, fixed label gap, anchors, `share_src`/intrinsic glue; C.5 kerns kept, `Tm` per run. P5 (kerns must stay). |
| 7 inserted-character ownership | C.1 owner rule (no label, no space-only body, font, `/Lang`, caret side), `edit_caret` in the request, prefix/suffix trim; C.6 (m); S5 tests. |
| 8 paragraph text | A.6: `synthetic` flag -> `inferred_ws`; `join_sep`; whitespace run = one position; hyphen join kept; A.2.a marker on the first run, not `_RE_NUMBERED_BULLET`. P2. |
| 9 grouping | A.1 column measure and "full" by first-word fit; A.2.a extra condition; A.3 single line-based candidate, stop on failure; A.4 owner sets (veto, unknown, positive cue); one flag for splits, merges and text. |
| 10 Q2 | C.0, C.3, sections 3 and 9. |
| 11 slices and tests | S1 page pass + census before grouping; test rule at the head of section 6; S0 probe 1 (real reflow regroups and rebinds) moved to the front. |
| new (P5) ids not stable | A.5: no id kept across a mutation, `paragraph_anchor`, `paragraph_at`; E takes anchor points. |

## 12. Review round 3 -> revision 4 (finding ids of `paragraph-grouping-reflow-review-r3.md`; P = probe)

The r3 record attributes every finding below to a group; it does not attribute m5 and m7 (their text was
not kept in the record), so they are not answered here by id.

| Findings | Resolution in revision 4 |
|---|---|
| X1 (blocker), M1 epoch restored while orphans are dropped | C.7 opening facts; no epoch branch; `ensure_donor` (digest at the recorded xref, else by digest, else re-embed, else STALE); redo proves F0, requires `inv_present` and (`inv_present`, S2); S6a test of commit -> undo -> save over open -> redo. P7. |
| X2 command also captures the one-stream reversal | C.7 donor commits: no `_capture_tier0_reversal`, `_tier0_*` stay `None`, record dispatch first; S6a test. |
| X3 (blocker), M2 undo/redo without transaction rollback; relocation reused unchanged | C.7 undo/redo: rollback captured at the start of the call, restored on any failure, starting state required, then STALE. States proven by `inv_absent`/`inv_present` + exact stream bytes; the patch is keyed to the current fingerprint after the proof; forced order (undo: stream then key; redo: key then stream). Today's relocation is used only for stream-only commits. |
| m1, m2, m3 direct `/Resources` effects | C.7 `remove_font_resource`: source form recorded; inherited form restored when contents are equal; result must equal the recorded `inv_absent`; indirect -> direct stays (invisible to both fingerprints). Copy-on-write orphan (new finding of this revision) removed by not replaying page bytes. |
| X4, m6 `Tw`/`Tz` | Section 4 terms: effective `Tw` 0 / `Tz` 100 at every show; C.5 prologue; S1 and S5 tests. |
| X5, M3 kerns | B.1 `array_linked` + kern slot; C.5 run origin (glyph origin without leading kern, or the verbatim text-matrix case), trailing kerns dropped, implicit 0 slot with string split; S5 tests. |
| M4 join glue, typed spaces | C.1 mask positions and lead-ins after an edit (`opp_cjk`, `Tc`); a join space that lands mid-line and a typed space are space atoms; whitespace exempt from the non-empty-glyph rule; A.6 no join space after trailing whitespace. |
| X6, M5 wrong outputs pass verify | C.6 (a) bijection on the replayed emitted stream, (g) 1-5 independent of plan coordinates, size in (h), (j) per glyph with `T` below the smallest glyph mask, (i) effective clip over all enclosing scopes (B.0 clip chain, non-coalesced lex); S5 wrong-output controls. |
| M6 ink box source | B.0 ink box from the glyph-id renderer, one source for C.4, (i), (j); `glyph_unit_box` not used. S0 probe 6 measures cost. |
| m8 (f)/(g) details | (f) advance end; (g) replayed positions, exempt pairs listed. |
| X10, m4 structure closure; simple-font route | C.7 closure digest (reference-free owner chains with `/K` index, not checked at undo/redo, never cached: B.0); `route_gids` with agreeing routes (B.0). |
| X7, M8 preview transport, one-line overflow | C.7 preview transport, scratch rendering, Apply (growth offer, live re-plan, token equality); C.0 order; S5 and S7 tests. |
| m11, m12 serializer, caches, tokenless no-fit | B.1 KEEP serializer for the band clone; C.7 caches; C.4 `REFLOW_DOES_NOT_FIT` terminal. |
| X8 RTL | A intro and A.6: RTL paragraphs untouched by A; `tier2r:rtl`; S9. |
| X9 untagged list after a full line | A.2.a (ii) sibling item; positive and negative controls. |
| M7, m9 no measure, punctuation, headings, 2.c | A.1 unknown fullness; A.2.a (i) needs a known short line; A.3 unknown + equal owners, bracket stripping, "both sets empty"; A.4 heading and cell owners with `/RoleMap`; A.2.c owner exception; limits stated in section 8. |
| X11, m10 slices and tests | Section 6 test rule split at S5; census split (S1 B.0 evidence, S4 admission); S2 flag pair; S6a donor re-edit and line pitch; S0 probe 1 widened (wrap across a body, growth, pull-up, donor, line pitch, admission predicates). |
| owner 2026-11-14 pull-up | C.3 re-break range and baselines; C.6 (f)(g); S3, S5, section 7. |
| owner 2026-11-14 system donors in v1 | D; C.7 `embed_donor`; token donor identity; S6b; P8. |

## 13. Review round 4 -> revision 5 (finding ids of `paragraph-grouping-reflow-review-r4.md`)

Round 4 had one reviewer (Codex); the Opus half did not finish.

| Finding | Resolution in revision 5 |
|---|---|
| N1 older stream-only command STALE after a `/Properties` merge | C.7 stream-only commits: the equal-layout early return of `_relocate` is removed, the invariant comparison still gates; S6a sequence test. |
| N2 verbatim `Tm` after an insertion on the same line | C.5 origin of a run: verbatim only when the planned first-glyph origin equals the source origin; S5 test. |
| N3 two shows after one `Tm` | Section 4 terms: every show follows its own `Tm` (v1 admission, the reference shape); S4 refusal test. Cursor continuation in the replay is not added. |
| N4 explicit restyle dropped | C.0 `tier2r:restyle_requested`; overrides in the token preimage; S5 test. |
| N5 convergence on the edited line; pull-up unverified | C.3 convergence only after the changed span, whole-line equality; C.6 (g) 6 every soft break required; S5 tests. |
| N6 line pitch after a donor edit in S6a | Moved to S8. |
| owner 2026-11-14 "the tier is not the point" | C.0 note; no mechanism added for tier order. |

## 14. Review round 5 -> revision 6 (finding ids of `paragraph-grouping-reflow-review-r5.md`)

| Finding | Resolution in revision 6 |
|---|---|
| F1, X1, X2 (major) check (g) 6 | C.6 (g) 6 rewritten: natural end (expansion removed), the breaker's own unbreakable unit and kinsoku, effective measure (C.8 frame); S5 controls on a justified line, a date, a narrowed frame. |
| F2 rounding vs (a) | C.5 number format: planned origins derived from the rounded operands; S0 probe 2 widened. |
| F3 unchecked pairs | C.6 (g) 5: every adjacent pair, intrinsic lead-in recomputed from C.1 rules, share derived from the replay; S5 control. |
| F4 newline edits lost | C.1 `tier2r:hard_break_edit`; S5 test. |
| F5 N1 test green before the change | S6a fixture constraint and layout assertion. |
| F6 growth test in S5 | Moved to S7. |
| F7 failure reaches the font-changing rebuild | C.0 "No silent font change": post-admission failure terminal on every path; S5 test. |
| F8 record bookkeeping | C.7 undo/redo bullet. |
| X minor token list, wording | C.7 token preimage names `style_overrides`; "every change the invariant covers". |
| owner 2026-11-14 "what if it still falls to the font-changing path" | C.0: a font change only by explicit consent whose sentence names it (S7 test); census in S4; open question in the top block (substitute font for inserted characters only). |

## 15. Review round 6 -> revision 7 (finding ids of `paragraph-grouping-reflow-review-r6.md`)

| Finding | Resolution in revision 7 |
|---|---|
| M1 one fit definition, legality, `join_sep` pair | C.3 defines line content, hanging whitespace, natural width, available width, legal break, unit, fits, `break_lines`; B.1 lists the `join_sep` pair; C.6 (g) 5/6 call the functions; S3 tests. |
| M2 alignment, zero opportunities | B.1 "Left anchoring": admitted on proof, else `tier2r:alignment`; one-line segments follow Q3; (g) 1 loses the centre/right clause; share 0 without division. |
| M3 which new line is justified | B.1 "justified paragraph" needs two agreeing lines (the widest line alone is no evidence, D5); C.3 "Share" is the one rule; (f) and (g) 5 use it. |
| M4 admission vs plan failure | C.0 classified by code: every `tier2r:` refusal continues; terminal = `REFLOW_DOES_NOT_FIT`, `PREVIEW_STALE`, `tier2r_commit_failed`; C.4, C.7 Apply, S5, S7 follow. |
| M5 verbatim threshold | C.5: verbatim only when d = 0 (1e-6). |
| minor S0 probe 2 | Asserts (a), (g) 5 and raster identity for the re-justified line. |
| minor one-line Tier 0 overflow wording | C.7 preview transport and the S7 test reworded. |
| minor C.7 citation | `edit_commands.py:859-861, 932-937`. |
| minor rebuild offered for terminal codes; consent text | `_NOT_REBUILDABLE` gains the two terminal codes (S7 test). Consent verified: the sentence names the font (`pdf_controller.py:3762-3763`), the default is No (`view/message_boxes.py:42-52`); `:4206-4207` was only the move replay. |
| minor C.8 vertical move | C.3 "effective geometry" covers anchors, baselines and measure; (g) 1, 3, 4 cite it. |
| minor typo fix re-flows | S0 probe 7 and an S3 test: an unchanged paragraph returns its own lines. |

Desk-run of the round-5 and round-6 counterexamples against the revision-7 text (by reading, not executed;
S3 turns each into a test):
- `the quick ` over `brown`: the content is `the quick`, the space hangs. Fits counts the space and
  `brown`; when that exceeds the available width the break stays, and (g) 6 re-runs the same function.
- Atom-less `join_sep`: "L followed by U" materializes the space, in the breaker and in (g) 6 alike.
- First atom with a lead-in: excluded from the natural width; slack is max(0, ...), so no negative share.
- Line with no opportunity: share 0, no division. Centred or right-aligned paragraph: refused at admission.
- Deletion on a justified line with the old breaks kept: `break_lines` on the replayed atoms pulls the
  next unit up, the partition differs, (g) 6 fails.
- Three opportunities at d = 0.004: not copied verbatim; the kern slots are rewritten to the C.3 share.
- `2026年11月14日` at a break: units come from legal breaks only, the same in the breaker and in (g) 6.
- Narrowed frame: effective geometry in the breaker, (f) and (g).
- Ragged paragraph whose widest line reaches the measure: not justified without two agreeing lines.
- `glyph_unavailable`, `clip_too_tight`: continue to Tier 0/1; never a dead end.

## 16. Review round 7 -> revision 8 (groups of `paragraph-grouping-reflow-review-r7.md`)

| Finding | Resolution in revision 8 |
|---|---|
| A (R N1, X3) share and (g) 5 on lines that were not re-laid | C.3 "Scope": laid-out vs kept lines; share, gap, (f), (g) 5/6 on laid-out lines only; (g) 4 covers every kept line, lines before the range included; C.5 d = 0 on kept lines; S5 test with compressed producer gaps. |
| B (R N2, X1) left anchoring | B.1: per paragraph, one continuation x0 for all lines but the first, competing centre/right evidence refused, n = 1 needs a label, equal starts or column evidence, the one-line exemption is for a one-line paragraph; S4 cases. |
| C (X4, R m8) justification evidence | B.1: justified needs widened gaps (`share_src` > 0.02 pt on at least half of the non-last lines with an opportunity), ends must agree; works for a two-line paragraph; `opp_cjk` from last lines (not circular); em defined in C.3. |
| D (R N3) measure | C.2: largest line end; D5's wall only for a one-line paragraph. |
| E (R N4) range start, frame change | C.3: range start one line earlier when the break into the edited line must be re-decided; frame change re-breaks every segment, unchanged text included; pure move keeps lines; (g) 6 recomputes the range start; C.8. |
| F (X2, R m1) `share_src` division | B.1: 0 without an opportunity, sums over the C.3 content. |
| m2 masks for (g) 6 | C.6 (g) header: inputs include the C.1 masks. |
| m3 whitespace-only unit | C.3 Fits. |
| m4 compensation wrong | C.6 (g) header corrected; S3 reference implementation on seeded random sequences. |
| m5 unclassified failures, Apply wording | C.0 (1) and (2). |
| m6 probe 2 line | S0 probe 2 uses item 1 line 1. |
| m7 (f) margin, CropBox floor | C.6 (f) 0.31 pt; C.4 floor. |
| after the merge | Citations updated (`pdf_model.py`, `pdf_controller.py`, `view/text_editing.py`, `view/message_boxes.py`); probe P9 (section 2). `edit_commands.py`, `inspect.py`, `pdf_text_edit.py` citations are unchanged by the merge. |

Desk-run against the revision-8 text (by reading, not executed):
- Justified paragraph, hard break after line 3, line 4 ends 0.2 pt short, a word typed on line 1: line 4
  is a kept line, translated, d = 0, checked by (g) 4 only.
- Centred `[30,70] [0,100] [0,100]`: continuation starts agree, start(F) differs, all midpoints agree:
  refused. F = 128-500, C1 = 200-400, no label, no column evidence: refused.
- Ragged Latin 100 / 100 / 30 with natural gaps, 10 pt deleted from line 1: `share_src` is 0, the
  paragraph is ragged, line 1 is not stretched.
- Item 1, line 1 edited (the widest line, ends 539.2): measure 539.2, lines fill to it, not to the wall.
- 日 deleted before `，` at the start of line 2: the break before `，` is illegal, the range starts at
  line 1, `，` stays with the atom before it.
- Right edge moved 40 pt left, one character typed on line 3: every segment is re-broken from line 1.
- Three single unbreakable words 100 / 100 / 30: no opportunity, `share_src` 0, ragged.

## 17. Review round 8 -> revision 9 (finding ids of `paragraph-grouping-reflow-review-r8.md`)

| Finding | Resolution in revision 9 |
|---|---|
| C1 (blocker) `inferred_ws` pairs enter the share | B.1 "Share pair": only CJK/CJK pairs and pairs after a whitespace atom; `inferred_ws` / `join_sep` pairs keep their source gap; C.3 share denominator, gap, C.5 d and (g) 5 use share pairs; S3 test with kern-made word spaces. |
| C2, X2 tracking taken for justification | B.1: baseline per class from last lines, no 0 fallback (ragged without one), `share_src` clamped at 0, uniform-tracking guard (5); stated limit. `Tc` is not subtracted as such because the reference justifies through `Tc .24` on some shows. |
| D2 hanging punctuation | B.1 refusal `tier2r:hanging_punctuation`, narrowed to the case where only the punctuation protrudes; S4 test and census. |
| X1, A1 kept lines vs (g) 1 | (g) 1 on laid-out lines only; C.2 anchors a laid-out line at the start of the source line whose baseline it takes; (g) 4 tolerance 0.001 pt; (f) wording. |
| B1 | start(F) = first body atom; "proven by the n >= 2 clause"; `column_starts` in the bind target. |
| E1 | C.3: an emptied line starts the range one line earlier. |
| E2, X minor 4 | Frame change triggers on a changed available width; pure move has precedence. |
| D3 | C.2 stated limit. |
| X minor 3 | S3 expectation corrected. |
| m2 nit, m5 | Masks list `inferred_ws`; C.7 Commit names `tier2r_commit_failed`. |
| C.0 note (pre-patch exception makes the paragraph uneditable) | Designer's choice under the owner's rule "the font must not jump": before a patch set an unexpected exception is `tier2r:internal_error` and the chain continues to Tier 0/1; after it, terminal. |
| wording | Heading, section 3 (D5), "Section E". |

Desk-run against the revision-9 text (by reading, not executed):
- Latin, one `TJ` per line, word gaps by kerns: no share pair on any line -> ragged; a pulled-up word
  keeps its source gap (`inferred_ws` pair), the join across the old line end gets a materialized space.
- Ragged Latin tracked `Tc` 0.5, ends 280 / 150: `base(space)` 0.5 from line 2, `share_src` 0 -> ragged.
- CJK grid, last line without a CJK/CJK pair: no baseline -> ragged.
- CJK lines 1-2 `Tc` 1, last `Tc` 0, ends 109/109/30: `share_src` 1 = T1 - T0 -> ragged by (5).
- Ends 539.2 / 553.2 (hanging `，`) / 300: single widest line, punctuation last, without it 539.2 ->
  refused `tier2r:hanging_punctuation`.
- Continuation starts 104.66 / 104.86, edit on line 1, line 2 converges: line 2 is kept, (g) 4 only.
- Reference item 1: `base(cjk)` from line 3, lines 1-2 widened by kerns and `Tc .24` on SOME shows (not
  uniform), ends 539.2 / 539.0 -> justified.

## Running log

- 2026-11-13 (Sonnet): diagnosis of the split paragraph; frames of the reference video reviewed.
- 2026-11-13 (Fable): found the unbuilt `plans/paragraph-reflow.md`; ran the baseline edit (section 1);
  probed fonts, stream shape, glyph-program identity, donor premise, hhea line height, structure tree,
  multi-`Tm` emission identity (section 2); design revision 1. Owner answered OD-1..3 and approved the
  direction.
- 2026-11-14: adversarial review round 1 (deep-reasoner, 16 findings; Codex `gpt-6.1-sol`, 15 findings),
  both NOT CONVERGED. Blockers checked against the code (`marked_content.py` struct-content class and
  pure-layer gate, `pdf_text_edit.py` terminal `PREVIEW_STALE`, `patch.py` one-stream reversal). Revision
  2 written (section 10). No product code changed.
- 2026-11-14: review round 2 NOT CONVERGED (record file). Six probes run on scratch copies (section 2,
  scripts `r3_*.py`). Checked in code: `xref_epoch` (`pdf_model.py:840, 936-939`), content relocation
  (`edit_commands.py:677-741`), `page_fingerprint` inputs (`inspect.py:791-836`). Revision 3 written
  (Fable; section 11). Q2 scope recorded (sections 3, 9). No product code changed.
- 2026-11-14 (Fable): review round 3 NOT CONVERGED (record file). Owner decisions recorded (section 9).
  Probes P7 and P8 run (section 2). Checked in code: epoch restore sites (`pdf_model.py:4883, 4990, 5810`),
  `_ContentWalker` and the inherited-resources fold (`inspect.py:874-1030`), `build_reversal_patchset`
  (`patch.py:193-251`), preview DTOs (`preview.py:69-119`), engine cache (`engine.py:112-131`). Revision 4
  written (section 12). No product code changed.
- 2026-11-14 (Fable): round 4: Codex NOT CONVERGED (N1-N6), Opus cut by the usage limit (record file).
  Owner: the tier is not the point, the font must not jump. Revision 5 written (section 13).
- 2026-11-14 (Fable): round 5 NOT CONVERGED from both (0 blockers; record file). Owner asked what happens
  when an edit still falls to the font-changing path. Revision 6 written (section 14).
- 2026-11-14 (Fable): round 6 NOT CONVERGED from both (0 blockers; record file). Owner: only newly typed
  characters may use a substitute font, after v1; asked whether refusing centred/right alignment is
  stable and which line is justified. Revision 7 written (section 15).
- 2026-11-14 (Fable): round 7 NOT CONVERGED from both (0 blockers; record file).
  `merge/security-remediation` merged into the branch; probe P9 run; citations updated. Revision 8
  written (section 16).
- 2026-11-14 (Fable): round 8 NOT CONVERGED from both (record file). Stopped; revision 9 not started.
- 2026-11-14 (Fable): revision 9 written (section 17).
