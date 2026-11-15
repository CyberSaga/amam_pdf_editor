# Paragraph grouping + original-font reflow: review round 12 (narrow)

Date: 2026-11-15. Subject: `plans/paragraph-grouping-reflow.md` revision 12 (section 20). Reviewers,
independent: deep-reasoner (Opus) and Codex (gpt-6.1-sol). Scope: the hanging-punctuation rule as changed
in revision 12 (C.2 `hang_room`, C.3 "Hangs" reach and reserve, `NO_LINE_START`, C.4 ink preflight and
`tier2r:ink_collision`, C.6 (f), (g) 7, (i), limit (c), S3-S5). All counterexamples are desk arithmetic;
nothing was executed.

**Verdict: NOT CONVERGED from both. No blocker. One major each, and they are different findings.**
S0 does not start.

## Status of the round-11 findings

R11-1, m1, m2, m4, m5, m6, m7: RESOLVED from both. m3: Codex RESOLVED for the reported (ragged) case,
Opus PARTLY (justified paragraphs, see N2).

Both confirm: `hang_room` is deterministic and not circular (source page pass, effective geometry,
variant; one function for planning, (f), (g)); `tier2r:ink_collision` is raised before any patch set,
leaves the document untouched and continues the chain (`PREVIEW_STALE` at Apply); no case needs a
re-layout instead of the refusal; B.1, C.3 and (f) share one `NO_LINE_START`; for a font size of
0.6 pt or more, no plan that passes "Hangs" fails (f), (g) 7 or (i) through the mark's position.

## Open findings

### C12-1 (major, Codex): the justified reserve can be smaller than the fit tolerance
Plan 568-573: body natural width <= available width + 0.3 pt; reserve = 0.5 em when justified and a
share pair is in front of the mark.
- M = 100, anchor 0, justified, em 0.4 pt, share pair in front. Body natural end 100.29 (slack 0,
  share 0). Mark: `ilead` 0, advance 0.4, ink right edge 0.1. CropBox and clip end at 100.60, so
  `hang_room` = 0.60. Reserve 0.20, reach 0.60: "Hangs" passes, the preflight passes (ink ends 100.39).
  e = 100.69; verify needs e <= 100.31 or e <= 100.61. (f) and (g) 7 fail terminally.
- Only for em < 0.6 pt; no minimum size is stated in these rules.
- Fix: reserve = max(0.3 pt, 0.5 em) in that branch; the boundary case in S3, an exact-emission
  positive control in S5. (Opus's exact reach, N2, removes the case as well.)

### N1 (major, Opus; new in revision 12): the ink preflight has no place in the C.4 order and no object set for the shift variant
Plan 634-636 ("Planning runs check (i) ... on the planned ink boxes before any patch set exists").
- Shift variant: C.2 says "the paragraphs that shift are not objects of that band" (536); the preflight
  says nothing. (i) at verify reads the patched scratch (shifted paragraphs lower); at planning the
  source page pass has them at the old places. Item 1 baselines 100/120/140, pitch 20, size 14; item 2
  first baseline 166 (ink y 154-168). An insertion adds line 4 at baseline 160 (ink 148-163); it does
  not fit, the shift variant moves item 2 down 20 (ink 174-188). The preflight against the unshifted
  item 2 sees 148-163 over 154-168 and refuses: no shift token is offered, or the live re-plan at Apply
  ends in `PREVIEW_STALE`. Contradicts 628-631 and the tests at 1137-1140.
- Order: if the preflight runs before the floor test (624-627), a growing edit that does not fit
  becomes the non-terminal `ink_collision` (chain continues to Tier 0/1) instead of the terminal
  `REFLOW_DOES_NOT_FIT` with its growth offer. `clip_too_tight` has the same unstated order.
- Fix, one sentence in C.4: the preflight runs after the fit test, on the `fit` plan only when it fits
  and on the shift variant otherwise; its object set is the variant's, the same set C.2 uses (shifted
  paragraphs at their shifted positions, the edited paragraph's own source glyphs excluded);
  `clip_too_tight` takes the same place. Test: a shift variant whose new line overlaps item 2's old
  position commits.

### Minors
- N2 (Opus): m3 still open for justified paragraphs. 14.04 pt, M 575, CropBox 595.3 (`hang_room` 20.3);
  source line 1 body ends at M with share 0.15, `，` ends at 589.19. A same-width typo fix re-lays the
  line: reach 0 + 7.02 + 14.04 = 21.06 > 20.3, `字，` is carried down (can become `REFLOW_DOES_NOT_FIT`).
  The rule also reserves 7.02 on a segment's last line, whose share is 0. Fix: reach = max(0, natural
  body width - available width) + `ilead` + (the line's C.3 share if a share pair is in front, else 0)
  + max(advance, ink right edge); or state the simpler bound as a limit and count it in the S4 census.
  Codex notes the ragged analogue: room 14.20 and a 14.04 mark fails by the 0.3 reserve; B.1's no-room
  exception permits it.
- N3 (Opus; Codex notes the same difference as conservative): (i) lists glyph ink, drawing, image,
  annotation; C.2 also lists widget and Form XObject and names the boxes. Conservative for a hanging
  mark; for an ordinary glyph a Form XObject rect at M + 0.1 is met by ink at M + 0.2 and nothing
  fails (admission of Form XObjects at 399-402: UNVERIFIED). Fix: (i) uses the C.4 object list with
  C.2's boxes.
- N4 (Opus): the positive overhanging-ink control (reach 21 <= 22: hangs, passes the preflight,
  commits) is only in section 20; add it to S3/S5.
- Nits (Opus): reach == `hang_room` lets ink touch x0 while (i) says "meets" (write `<` or define
  "meets" as open); the probe's `MARKS` lacks `〉》｝］”’`, uses rawdict char boxes and the next text line
  as floor, so P2c's 56.40 is evidence, not the C.2 value; state the band's y-range under a move in
  effective geometry; a larger mark pulled up can have ink above the band top (the preflight catches
  it, non-terminal).

## UNVERIFIED (both)
The reference's ink geometry and effective clip right edge (S0 measurement).

## Next
Revision 13: N1 (order + object set of the preflight, shift-variant test), C12-1 / N2 (exact reach, or
reserve = max(0.3 pt, 0.5 em) with the limit stated), N3, N4, nits; top block back to 40 lines. Then a
narrow round 13 on the preflight order/object set and the reach. S0 only on CONVERGED from both.
