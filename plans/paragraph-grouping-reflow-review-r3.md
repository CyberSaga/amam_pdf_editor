# Review round 3 of `paragraph-grouping-reflow.md` revision 3 (2026-11-14): NOT CONVERGED

Record of both independent reviews, condensed, so revision 4 can be written without the transcripts.
R = deep-reasoner (Opus): no blocker, 8 majors (M1-M8), 12 minors (m1-m12). X = Codex `gpt-6.1-sol`: 2
blockers, 8 majors, 1 minor (X1-X11). Evidence lines are the reviewers' citations; (checked) = re-read by
the main model. Nothing is implemented.

## Rows of section 11 (R / X)

| Group | R | X |
|---|---|---|
| 1 emission unit | RESOLVED | PARTLY (`Tw`/`Tz`) |
| 2 donor transaction | PARTLY | PARTLY |
| 3 preview/token | PARTLY | PARTLY |
| 4 colour/clip | PARTLY (enclosing-scope clips) | RESOLVED |
| 5 identity/verify | PARTLY | PARTLY |
| 6 glue | PARTLY | PARTLY |
| 7 ownership | RESOLVED | RESOLVED |
| 8 paragraph text | PARTLY | PARTLY (RTL) |
| 9 grouping | PARTLY | PARTLY |
| 10 Q2 | RESOLVED | RESOLVED |
| 11 slices/tests | PARTLY | PARTLY |
| new: ids | RESOLVED | RESOLVED |

Both accept: the body unit makes the output admissible again (text state cannot leak past `Q`); ids are
never kept; owner rule for inserted characters; Q2 scope; `q_open_offset` keeps the coalescing contract;
the commit-path order F0 -> F1 -> F2 is gate-consistent; S0 probe 1 is a sound gate for the reference shape.

## Open findings, grouped by the plan change they need

### 1. Donor transaction (X1 blocker, X2, X3 blocker, M1, M2, m1, m2, m3)
- Save-over-open RESTORES the epoch (`pdf_model.py:5810-5814`, checked; also `4883-4885`, `4990-4993`,
  `5417-5437`), while the saved file has dropped unreferenced objects (P1). Commit -> undo -> save over the
  open file -> redo takes the "same epoch" path with the donor xref now `null`; PyMuPDF skips non-dict font
  entries (`pymupdf/__init__.py:19505-19508`), and nothing compares the F1 read against the recorded F1.
  Change: correct the epoch sentence; before any redo check the donor's content digest at its xref, else
  re-create or STALE; redo in any epoch requires fingerprint = recorded F1 before the stream and F2 after
  (no re-verify, the result is byte-identical); S6 test for exactly this sequence.
- A command with `retypeset_record` must NOT also capture the one-stream reversal: `execute` calls
  `_capture_tier0_reversal` for every high-fidelity tier (`edit_commands.py:452-458`, `dto.py:244-247`);
  `_redo` goes to `_redo_tier0` when a forward patch exists (`:513-514`); its forward patch is keyed to F0,
  so after a record-driven undo, redo would apply a stream using `/FD1` to a page without it, and the F0
  gate passes. Change: record-driven `undo`/`_redo` first; `_tier0_*` stay `None` for such commands.
- Undo/redo need the same transaction-wide rollback as commit: capture page object and stream storage at
  the start, restore both on any failure, verify the start state, then STALE. "Re-apply the stream patch"
  is wrong (it expects F1) and leaves a half-applied page.
- Existing relocation cannot be reused unchanged: one stream-elided invariant taken after commit
  (`edit_commands.py:610-615, 726-735`), and `_apply_retained_patchset` assumes non-stream inputs do not
  change (`:787-800`). Order is therefore forced in another epoch (undo: stream then key; redo: key then
  stream), with separate expected invariants for the resource-present and resource-absent states and
  re-keying of the record after a relocation.
- Direct `/Resources`: indirect -> direct is invisible to both fingerprints (`inspect.py:847-849`);
  INHERITED -> direct changes the marked-content fold (`marked_content.py:113-126`) and the invariant
  (`inspect.py:1021-1030`), so leaving the direct copy after an other-epoch undo makes earlier relocatable
  commands on that page STALE and changes `/Properties` admission. Change: record the source form; remove
  the direct copy when its content equals the inherited dictionary; require the invariant to equal the
  recorded F0 invariant, else roll back. (X asks instead for canonical effective-resource hashing.)

### 2. Emission (X4, X5, m6, M3, M4)
- `Tw`/`Tz`: admission allows `0 Tw`/`100 Tz` in the body, emission drops them, and inherited values are
  not checked; the kern formula ignores Th (`glyph_boxes.py:367, 399`). Change: admit only EFFECTIVE Tw 0
  and Th 1 at every source show (replay state) and/or emit `0 Tw 100 Tz` at the start of each rewritten body.
- Kerns: a CJK run in one string has break opportunities with no numeric kern (materialize an implicit 0);
  a leading kern is already in the first glyph's origin, so `Tm` at the glyph origin + keeping the kern
  applies it twice (distinguish text-matrix origin from first-glyph origin; define who owns leading and
  trailing kerns of a slice).
- Glue at a source-line join is undefined (every wrap creates such pairs): last atom of a source line gets
  its body's Tc x Th + `intrinsic_opp` at a CJK/CJK join; a surviving Latin `join_sep` becomes a break
  opportunity with the line font's space advance + `intrinsic_opp` (carried by `Tm` or a real space atom);
  no `join_sep` when the line already ends in whitespace (`text_block_parsing.py:208-213`).
- Typed spaces are refused by "non-empty glyph" (`glyph_boxes.py:720-721`): exempt whitespace; an inserted
  space is a space-glyph atom of the owner body's font or the paragraph's space font, with a width entry,
  a break opportunity with glue `intrinsic_opp`.

### 3. Verification (X6, M5, M6, m8, X10/m4)
- Wrong outputs that still pass: a whole ragged line translated 2 pt (origins are checked against the plan
  only); an extra inkless glyph (duplicated space); a glyph hidden by a clip of an ENCLOSING non-top-level
  scope (B.0 flags top level only; `T` may be as high as ~2000 px); a donor run at a slightly wrong `Tf`
  size. Change: (a) becomes a bijection: replay the emitted stream, its predicted glyphs for the rewritten
  bodies equal the planned atoms exactly (0.001 pt), then trace-join at 0.3 pt; independent checks for
  fixed anchors, label-to-body displacement, permitted baseline changes and untouched-tail positions; size
  in (h); `T` of (j) per planned glyph box and below the smallest single-glyph mask; W/W* of every
  enclosing scope in B.0 and (i) (needs a non-coalesced lex of the prefix: `replay.py:593-599`,
  `pdf_lexer.py:151-153`).
- (i) and `clip_too_tight` assume `glyph_unit_box` (raw glyf, refuses point-matched composites,
  `glyph_boxes.py:660-662, 732-749`) gives the rendered ink box; DFKai-SB may be a "tricky" face
  (unverified). S0 probe: compare with ink bounds from the glyph-id renderer for every glyph of item 1 and
  the donor glyphs; fallback: boxes from the renderer.
- (g) must use replayed positions and exempt pairs whose `inferred_ws`/`join_sep` was deleted; (f)
  measures to the advance end.
- Structure closure: "references elided" is not what the invariant does (it substitutes referenced
  content, `inspect.py:893-906`) and would lose the MCID -> owner mapping. Specify a reference-transparent
  canonical form keeping that mapping and `/K` order; do not re-check at undo; the page-pass cache key must
  include the closure.
- Simple-font prediction needs a code -> gid route: `simple_font_programs.route_gids` (`:353-361`), all
  routes agreeing.

### 4. Preview / token / dialog (X7, M8, m11, m12)
- `controller/text_commit_coordinator.py:173` builds Tier 0-shaped requests; the result has one `prepared`
  (`preview.py:119`); the Controller caches one token + image (`pdf_controller.py:5568`); Apply is disabled
  without `current_plan_token()` (`view/text_editing.py:3045`), so a no-fit result without a shift token
  cannot open a dialog "at Apply time".
- A one-line paragraph with a Tier 0 target gets a Tier 0 session; when typing overflows, Tier 0 refuses
  and Tier 2R never previews. The scratch `PreparedRetypeset` never reaches the live engine cache
  (`engine.py:116-131, 284`).
- Change: the request carries both targets and the worker runs Tier 0 then Tier 2R (commit-chain order);
  tokens carry a kind prefix; Apply re-binds and re-plans on the live document and compares tokens
  (mismatch or verify failure is terminal); a generation-bound "growth decision available" state enables
  the dialog without a tokenless commit; define caching/presentation per variant; the band-background
  clone uses the KEEP serializer (`preview.py:164-198`); page-pass cache per document, plain data
  (scratch and live fingerprints are equal); font-discovery cache locked; tokenless path:
  `REFLOW_DOES_NOT_FIT` is terminal (must not fall into the consented rebuild).

### 5. Grouping and text (X8, X9, M7, m9)
- A.6 "in x order" reverses RTL text (`text_block_parsing.py:416, 457`): make it direction-aware or bypass
  A for RTL in v1.
- Untagged list whose item-1 last line is full: nothing splits item 2 (MuPDF already fuses them), and
  Tier 2R would reflow the label `2.` as body text. 2.a must also fire on an outdent (x0 < previous x0 - 1
  pt); add the negative control.
- With no measure nothing is "full": 2.a then splits at `3.5 percent` in ragged text, and two same-owner
  single lines never merge. Punctuation veto misses `。」`/`。）`; owner sets ignore `/H1`-`/H6`; "no owner
  evidence for either line" is ambiguous; 2.c can split a hard-broken hanging paragraph with one owner.
  Decide and state which are intended conservative limits.

### 6. Slices and tests (X11, m10)
- The head-of-section rule (show a Tier 2R commit first) cannot run in S1/S4; use page-pass/binder result
  assertions there and commit-path controls from S5. The S1 census needs B.1 (S4) and A (S2): move it or
  limit it to B.0 evidence. The S2 flag-off dump test is a regression guard, not a red test: pair it with
  a flag-on difference. Add S6: donor edit -> re-index -> second edit and line pitch. Widen S0 probe 1:
  wrap across a body, growth, a deletion, a donor run, E after an edit, and assert the BINDER binds.

## Handoff

Next: write revision 4 of sections 4-6 against the six groups above (add a "round 3 -> revision 4" table),
then review round 4 the same way (deep-reasoner `opus` + `codex:codex-rescue` with `--model gpt-6.1-sol`,
parallel, read-only, ~10-25 min each). S0 only when both say CONVERGED. Group 1 is the only one with
blockers; a cheaper v1 that would remove most of it: in-document donors only and no system donor (no
created objects to lose), decided by the owner.
