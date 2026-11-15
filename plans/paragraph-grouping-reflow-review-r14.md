# Paragraph grouping + original-font reflow: review round 14 (narrow)

Date: 2026-11-15. Subject: `plans/paragraph-grouping-reflow.md` revision 14 (section 22). Reviewers,
independent: deep-reasoner (Opus) and Codex (gpt-6.1-sol). Scope: what revision 14 changed (one object
set, Forms by what they paint, `tier2r:source_ink_overlap`, "meets" > 0.01 pt on planned boxes, the
shortening exception, test fixtures). Desk arithmetic only; nothing was executed.

**Verdict: NOT CONVERGED from both. No blocker. One major each (different findings).** S0 does not start.

## Status of the round-13 findings

R13-1, R13-3/F2, R13-6, nits: RESOLVED from both. F1/R13-4: PARTLY from both (the three examples are
resolved; what is left is C14-1 and the last bullet of R14-1). R13-2/F3: PARTLY from both (R14-3).
R13-5: RESOLVED for (i) (both); Opus PARTLY because of (c)/(j) (R14-1).

Both confirm: one object-set definition, read by C.2 (c), the floor, the preflight, (i) and admission;
no operative rule still counts a Form by its BBox; the self-check is not circular; own-paragraph
exclusion handles label vs body; kept untranslated lines cannot cause `ink_collision`; a line re-laid
with unchanged text but moved geometry can (non-terminal, by design); no terminal (i) failure is
reachable from a plan that passed the preflight; the shortening arithmetic (0.025 -> 0.376, reach
14.065 -> 14.416 > 14.30, line 2 453.08, body 439.04 > 434.80) holds when the deleted digit keeps n = 20.

## Open findings

### C14-1 (major, Codex) = R14-2 (minor, Opus): obstacle boxes are not defined for glyphs the page pass cannot bind
Plan 637-640 ("glyphs not of this paragraph by their ink boxes ... as the page-level texttrace ...
report them") vs B.0 320-322 (ink box = font-program/gid mask) and 315-319 (texttrace gives the
basefont name only; unsuccessful joins leave shows unbound).
- Codex: M = 100; an unbound/Form glyph with true ink [105,115] x [10,20] and trace rectangle
  [103,117] x [8,22]; a mark reaching 106. Omitting the glyph permits the hang wrongly; the trace
  rectangle gives room 3 instead of 5; the true mask needs a route the plan does not give.
- Opus adds: foreign glyphs under a skewed/scaled/stroking text matrix (14 pt, tan 12 deg: 0.36 pt);
  stroked drawings whose `rect` may ignore the line width (zero-area hairline never "meets" under
  "> 0.01 on both axes"); shadings named by the uniform-background rule but absent from the object
  set (`sh` may be dropped from `get_drawings`). All UNVERIFIED for the compiled extraction path.
- Fixes offered: define obstacle records independently of binding; when exact ink is not available
  use a conservative bound (the texttrace per-character bbox) or a named refusal, never an omission;
  drawings/images/shadings from `get_bboxlog` (includes stroke and `fill-shade`); widen S0 probe 8
  (Form shading, stroked rule, compiled extraction, box of a Form glyph).
- Owner question 2026-11-15 ("with no font and only a rectangle, is that not already an engine
  failure?"): for the EDITED paragraph yes (`tier2r:show_unbound`, already in the plan); this finding
  is about neighbours that are only obstacles. Direction agreed in the session: the conservative
  rectangle, no recovery of the neighbour's exact ink.

### R14-1 (major, Opus): a plan that passes the preflight can still fail (c) or (j), terminally
- (c) 724: band = union of old and new LINE boxes grown by 1 px; "line box" is undefined. If it is the
  advance extent, the S5 positive control (ink right edge 16, advance 14) has ink 0.5-2.0 pt outside
  the band: the raster differs there, (c) fails, `tier2r_commit_failed`.
- (j) 787: mismatching pixels are counted inside each ink box GROWN by 1 px, and "the band outside all
  ink boxes holds no ink". A touch is legal for (i) (section 22's own run: reach = `hang_room`,
  overlap 0.003). Control with s = 6: reach 22 = `hang_room`, a filled border rect at M + 22: the
  border fills the ring column of the mark, T is about 1, (j) fails terminally. Also: a table cell
  with `hang_room` 10.6 and reach 10.44; a new line within 0.5 pt of the floor object.
- (j) draws its reference on "the band's uniform background", proven by admission only for the SOURCE
  paragraph band: growth lines, marks beyond the source extent and shifted glyphs lie outside it.
- F1 residue: a kept source `”` with ink box right at 545.00 and a filled border at [545.20, 545.95]:
  the self-check passes (no overlap), the background check passes (outside the band), every edit
  fails (j) on the kept mark's ring.
- Fix (two sentences): (c) and (j) use one band = old and new line boxes AND ink boxes of the
  rewritten bodies, grown by 1 px; every object box is grown by 1 px (0.5 pt at 2x) before each
  consumer of the object set (C.2 (c), floor, preflight / (i), admission self-check). Test: reach =
  `hang_room` - 0.2 beside a filled rect hangs and commits, or does not hang.
- Codex did not raise it; its F3 notes only a bounded gap (planned overlap 0.0095 + replay drift
  0.0008 = 0.0103, inside (a)'s tolerance).

### Minors
- R14-3 / C14-2 (both): the room-20 twin separates a correct from an advance-only implementation
  only for 4 < s <= 6: pin s = 5 and a share pair in front of the mark. Opus: the ink-23 fixture must
  give the neighbour's INK box x0 at M + 22; "the edit commits" must assert the Tier 2R tier and the
  line partition (Tier 0/1 would commit too); the shortening fixture must keep the deleted digit
  inside a digit word (n stays 20).
- R14-4 / C14-3 (both): "(i) at verify can only fail when the emission differs from the plan" (666)
  is wrong: (i) at verify re-runs the preflight on the same planned boxes. Say that it guards
  planning/verify divergence and that emission fidelity is (a), (b), (k), (l) within their tolerances.
- R14-5 (Opus): clip containment in (i) has no tolerance while "meets" has 0.01 (give it the same);
  S0 must run the self-check on the reference paragraphs; probe (6) must include foreign ink boxes.
- Nits (Opus): (i) hard-codes "PLANNED" boxes though admission calls it with source glyphs (make the
  tested set a parameter); the revision-14 shift tests belong to S7, not S3; d(1 + 1/n) holds only
  with a share pair in front of the mark; S4 lacks a CropBox case and a "touching neighbour still
  binds" control; 645 "nothing but text that B binds" -> "no object of the C.4 set other than the
  shifted paragraphs' glyphs"; "band" has three meanings (399, 534, 724).

## UNVERIFIED
What the compiled extraction returns for stroked rects, shadings and Form content; whether
`get_image_info` reports shadings; T after S0; CJK ink extents; the reference page's clip and Form
geometry.

## Next
Revision 15: C14-1/R14-2 (obstacle box = exact ink when bound, else the conservative rectangle; object
kinds and their boxes; probe 8 widened), R14-1 (one ink-inclusive band for (c)/(j); object boxes grown
by 1 px), R14-3, R14-4, R14-5, nits. Then round 15. S0 only on CONVERGED from both.
