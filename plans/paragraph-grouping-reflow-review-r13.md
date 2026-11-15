# Paragraph grouping + original-font reflow: review round 13 (narrow)

Date: 2026-11-15. Subject: `plans/paragraph-grouping-reflow.md` revision 13 (section 21). Reviewers,
independent: deep-reasoner (Opus) and Codex (gpt-6.1-sol). Scope: what revision 13 changed (C.3 "Hangs"
reach without reserve; C.4 "Order and ink preflight"; C.6 (i) object list and "meets"; their tests).
All counterexamples are desk arithmetic; nothing was executed.

**Verdict: split. Opus CONVERGED (no blocker, no major, 6 minors). Codex NOT CONVERGED (one major).**
So the plan is NOT CONVERGED; S0 does not start. Both raise the same defect (Codex F1 = Opus R13-4);
they differ on its severity.

## Status of the round-12 findings

C12-1, N2, nits: RESOLVED from both. N1: RESOLVED (Opus) / PARTLY (Codex: object-set wording, F2).
N3: RESOLVED as asked with a side effect (both: F1 / R13-4). N4: PARTLY from both (arithmetic, R13-2).

Both confirm: the reach is the planned right extent of the mark from M in every line shape (ragged
with b < 0, share > 0, slack 0 with the body up to 0.3 past M, share over the cap, a segment's last
line, a non-share pair in front, `。」`); nothing is circular ("Hangs" always evaluates the hanging
branch of Share); a plan that passes "Hangs" cannot fail (f) or (g) 7, and (g) 6 reaches the same
hang decision; the order is complete for fits / no fit with a variant / no fit without one / a `fit`
token at Apply / tokenless callers; withholding the shift token agrees with
`GrowthOffer(shift_token: str | None)`, dialog option a and the token preimage.

## Open findings

### F1 = R13-4 (major for Codex, minor for Opus): source overlaps refuse every edit
Plan 761-764: (i) "meets no object ... Form XObject by their rects"; admission (397-402) excludes
annotation/widget rects, image, shading, drawing in the band and "not inside a Form XObject", but not
another Form's rect, a neighbouring paragraph's ink, or source ink outside the CropBox or clip. (d)
makes the planned atoms the whole paragraph, so kept lines are tested.
- Codex: band [0,100] x [100,140], kept glyph ink [25,35] x [105,115]; another Form with rect
  [20,40] x [90,200] painting only at y 180-190. The emptied band is white, admission passes, every
  edit elsewhere in the paragraph is `tier2r:ink_collision`.
- Opus: a footer stamp whose /BBox is the whole page meets every planned ink box of the page; two
  paragraphs with a true ink gap of 0.2 pt and ink boxes grown to whole pixels at 2x (up to 0.5 pt a
  side) overlap by up to 0.8 pt, so every edit of either is refused.
- Non-terminal (the font is kept), but invisible to the S4 census and the reason is misleading.
- Fixes offered: an admission refusal (`tier2r:source_ink_overlap`: the source glyphs at their source
  positions fail the (i) function; census count, S4 test), or exempt proven unchanged source
  intersections; optionally count a Form XObject by what it paints, not its BBox. Tests for a kept
  line and a re-laid-unchanged line.

### Minors
- R13-1 (Opus; caused by revision 13): "A shortening edit always fits" (655) is false. On a hanging
  line with share > 0, s = slack / n grows when the body shortens. Justified, 14.04 pt, available
  434.50, `hang_room` 14.30, line 1 body 434.00 with 20 share pairs ending `字，`: share 0.025, reach
  14.065, hangs. Delete one half-width digit (7.02): share 0.376, reach 14.416 > 14.30, `字，` moves
  to line 2 (425.00 -> 453.08, body 439.04 > 434.80), `字。` goes to a new line 3: the paragraph grows
  by one pitch; with an object below it is `REFLOW_DOES_NOT_FIT` (terminal). Designer's choice: (A)
  state it ("fits unless a hanging mark loses its room because its line's share grew; that is
  ordinary growth") + an S3 test; (B) never stretch the gap in front of a hanging mark (s = 0
  always): reach only falls on shortening, but the mark of a justified line re-laid unchanged moves
  left by `share_src` (breaks the "keeps its positions" test, changes Share).
- R13-2 = F3 (both): the positive control says "reach <= 20"; with advance 14 and ink 13 it is
  7 + max(14, 13) = 21 (20 is the ink end), and the ink term is never exercised. Use ink right edge
  16 > advance 14 with s <= 5 (reach <= 21 <= 22). "reach 30 > 22" (1088) is stale; the "ink 23 -> no
  hang" fixture must pin b + ilead + s >= 0. Correct section 21's run too.
- R13-3 = F2 (both): C.4 calls its object set "the set C.2 uses" while C.2 says "the paragraphs that
  shift are not objects of that band"; one shared set would give the variant a `hang_room` of 0.84
  beside a shifted paragraph's own hanging mark. Unstated: which glyphs the variant tests, and that a
  glyph is never tested against its own paragraph (a shifted glyph [0,10] x [174,188] meets itself).
  Fix: "the C.2 set plus the shifted paragraphs at their shifted positions"; "on the variant, the
  clip test and (i) also cover every shifted glyph; a glyph is never tested against its own
  paragraph"; a shift positive control.
- R13-5 (Opus): a touch can become a hit through rounding: "Hangs" is exact, planned origins come from
  rounded operands, (a) allows 0.001 pt, shifted `Tm` y is rounded. At verify that would be terminal
  if (i) reads replayed boxes (the text leaves it open). Fix: "meets" = interiors overlap by more
  than 0.001 pt; (i) at verify tests the planned boxes, shifted paragraphs at the positions (k) proves.
- R13-6 (Opus, wording): (a) a `t2r:shift` token at Apply whose live variant hits: say
  `PREVIEW_STALE` (Codex: already covered by C.7 token equality, stating it helps); (b) 637-639 makes
  `clip_too_tight` unconditional, against 650-652 for the variant; (c) "an edit that does not fit
  never turns into a `tier2r:` refusal" is too broad (`unbreakable_overflow`, `glyph_unavailable`
  come before the floor test): narrow it to `ink_collision` / `clip_too_tight`.
- Nits (Opus): "never the mark" (579) is inexact, the em counts the mark; "exactly when no unit
  follows" is wrong for a trailing whitespace-only unit (conservative); the range-start argument
  (607-608) needs "and whether it is the segment's last unit"; "hangs again when re-laid unchanged"
  is exact for ragged lines only (a justified line whose plain end is d <= 0.3 short of M moves its
  mark d(1 + 1/n) right).

## UNVERIFIED
Whether "Form XObject by their rects" means the transformed /BBox and how common page-sized form
BBoxes are; whether `page_fingerprint` covers Form XObject contents; the reference page's effective
clip and ink geometry (S0).

## Next
Revision 14: F1/R13-4 (admission rule or exemption: designer's choice), R13-1 (choice A or B),
R13-2, R13-3, R13-5, R13-6, nits. Opus: a confirmation of the revision-14 diff is enough. Then
round 14 (Codex's verdict is the open one). S0 only on CONVERGED from both.
