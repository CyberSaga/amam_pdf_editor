# Review round 7 (narrow) of `paragraph-grouping-reflow.md` revision 7 (2026-11-14): NOT CONVERGED

Record for writing revision 8 without the transcripts. R = deep-reasoner (Opus): 0 blockers, 4 majors
(N1-N4), 8 minors (m1-m8). X = Codex `gpt-6.1-sol`: 0 blockers, 4 majors (X1-X4). Nothing is implemented.

## What both accept

- r6 M1 (one definition in C.3, `join_sep` pair), M4 (outcomes by code), M5 (verbatim only at d = 0) and
  all r6 minors: RESOLVED. Every code citation of revision 7 was verified by both. No regression in the
  donor transaction or section D. X's arithmetic checks of the r5/r6 counterexamples all hold.
- r6 M2 and M3: PARTLY (findings below).

## Open majors

- **A. Share and (g) 5 reach lines that were not re-laid (R N1, X3).** C.3 defines the share for "a new
  line" but (g) 5 checks every replayed line. On a kept or rigidly translated justified line the C.3 share
  differs from `share_src` by (measure - end)/opportunities, and by the whole `share_src` when it is
  negative (compressed producer gaps) or above the cap. A correct emission then fails (g) 5 (terminal),
  or an emitter that applies d fails (g) 4. Change: C.3 share, (g) 5 and (g) 6 cover ONLY the re-broken
  range; every other line keeps d = 0 and is checked by (g) 4 against source origins, lines before the
  first edited line included.
- **B. Left anchoring admits unproven shapes (R N2, X1).** (1) n >= 2 with agreeing continuation starts
  admits centred `[30,70] [0,100] [0,100]` and the right-aligned twin (X1). (2) The n = 1 clause (ends
  and midpoints differ) only excludes exact centring (R N2a). (3) The proof is per segment and exempts
  one-line segments, but the anchors are per paragraph; A.2.c keeps centred hard-break lines in one
  paragraph, so a centred address block is admitted and laid out from one x0 (R N2b). Change: the n = 0
  exemption covers a one-line PARAGRAPH only; every line except the paragraph's first must start at one
  continuation x0 (0.3 pt); refuse when F and the continuation lines share a midpoint or a right end
  while their starts differ (competing evidence); drop the n = 1 ends/midpoints clause, or require
  start(C1) to equal the continuation x0 of an admitted paragraph of 3+ lines in the same column. A
  paragraph that shrinks from 3 lines to 2 may flip to `tier2r:alignment`: safe (font kept).
- **C. Justification evidence (X4; R m8).** Two agreeing non-last ends are not proof: ragged Latin lines of
  equal natural width become "justified" and an edited line is stretched (5 pt per gap in X's example).
  Change: require affirmative evidence beyond coincident ends (for example `share_src` above a small
  threshold on those lines, i.e. the gaps were actually widened), otherwise share 0. R m8: a 3-line
  justified paragraph that shrinks to 2 lines is ragged on the next edit; state it as a limit or use the
  same `share_src` evidence. "0.5 em" needs a definition when a line mixes sizes.
- **D. The measure behind the share can be the D5 wall (R N3).** C.2 inherits D5, whose fallback
  (`paragraph-reflow.md:115-118`) is `_right_wall` when the edited line is the widest or the paragraph
  has at most two lines; B.1 says "D5's measure is the widest line". Editing the widest line of item 1
  would fill and justify to the wall (shift unverified: page size not recorded). Change: the Tier 2R
  measure is the paragraph's largest line end; the fallback only for a one-line paragraph (Q3); correct
  the B.1 sentence.
- **E. Where the re-break range starts (R N4).** (a) The break INTO the range is never re-decided or
  checked: deleting the first glyph of line 2 can leave it starting with `，`; deleting a long first word
  leaves a word that now fits on line 1. (b) Frame changes: with a narrowed right edge the lines before
  the edit keep the old measure; with a moved left edge (g) 1 fails on unmoved lines; a drag with
  unchanged text has no edited line (today `GEOMETRY_OVERRIDE_PRESENT`, `pdf_text_edit.py:5069-5078`).
  Change: re-break from the line BEFORE the first edited line (same segment); when the effective geometry
  differs from the source, re-break every segment, unchanged text included; (g) 6 includes the break at
  the start of the range.
- **F. `share_src` divides by zero (X2; R m1).** A justified source line with no opportunity. Change:
  `share_src` = 0 when there is no opportunity, computed over the C.3 content (trailing whitespace out).

## Minors (R)

- m2: (g) 6 must receive the C.1 masks (an atom-less `join_sep` otherwise looks like a break in a word).
- m3: in Fits, "hanging whitespace becomes interior" only when U has content (a double space could start
  a line).
- m4: the stated compensation is wrong: (c) checks outside the band and (j) compares against planned
  positions. The independent checks are (f) and (i). Add a test-only second implementation of C.3
  compared on random sequences.
- m5: failures before a patch set that are not refusals (renderer, texttrace, fontTools) have no class;
  C.7 Commit should name `tier2r_commit_failed`; C.0 (1) should say "on the preview and tokenless paths"
  (at Apply a live refusal is `PREVIEW_STALE`).
- m6: S0 probe 2 should use a line that ends at the measure (item 1 line 1).
- m7: (f) needs 0.01 pt rounding margin; the C.4 floor needs the CropBox bottom (growth off the page
  fails (i) terminally instead of `REFLOW_DOES_NOT_FIT`).

## Handoff

Revision 8: A-F and the minors; nothing else. Pattern of this round: revision 7 unified the arithmetic but
left its SCOPE loose (which lines it applies to, where the range starts, which measure) and trusted
coincident geometry as proof (anchoring, justification). After the merge of `merge/security-remediation`
(2026-11-14) re-check the plan's line citations in `pdf_model.py`, `pdf_controller.py`,
`view/text_editing.py`, `view/message_boxes.py` and re-run probes P1/P7 (saves now write object streams).
Then a narrow round 8. S0 only when both say CONVERGED.
