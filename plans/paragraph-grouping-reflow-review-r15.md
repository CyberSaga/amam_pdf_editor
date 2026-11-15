# Paragraph grouping + original-font reflow: review round 15 (narrow)

Date: 2026-11-15. Subject: `plans/paragraph-grouping-reflow.md` revision 15 (section 23). Reviewers,
independent: deep-reasoner (Opus) and Codex (gpt-6.1-sol). Scope: what revision 15 changed (C.4 "Object
set", fallback box, `get_bboxlog` sources, object margin 1.0 pt, verify band for (c)/(j), fixtures).
Desk work only; nothing was executed.

**Verdict: NOT CONVERGED from both. No blocker. One major each (different findings).** S0 does not start.

## Status of the round-14 findings

R14-3/C14-2, R14-4/C14-3, R14-5, nits: RESOLVED from both (one nit left: "shifted band" undefined).
C14-1: RESOLVED (Opus) / PARTLY (Codex, C15-1). R14-2: PARTLY (Opus, R15-1). R14-1: RESOLVED for
objects whose paint lies inside their box (both); residues R15-2..4 (Opus) and C15-1 (Codex).

Both confirm: one definition serves the five consumers; own-paragraph glyphs and the label are not
objects, so the margin does not self-collide; the reference passes (item 1 / item 2 line-box gap 6.96
pt, 5.49 pessimistically, against 2.0 needed; `hang_room` stays 56.40); the shift variant stays
possible (shifted paragraphs keep their gaps; impossible only where two shifted paragraphs are
within about 2 pt, non-terminal); for bounded objects 2 px is enough (object edge >= 1.98 px from the
planned box, ring 1 px): reach = `hang_room`, a line touching the floor box, a grown box overlapping
the verify band and the old boxes of a shortened paragraph all pass; section 23's desk runs are
arithmetically right.

## Open findings

### R15-1 (major, Opus): image masks are not in the object set
Plan 660-662 lists `fill-path`, `stroke-path`, `fill-image`, `fill-shade`. PyMuPDF's bbox device also
emits `fill-imgmask` (`pymupdf/__init__.py` 22676-22678, 23461) for `/ImageMask true` and inline
`BI /IM true`.
- M = 539.16, a stencil stamp at x [548, 580] in the hang band: as written `hang_room` 56.40, a `，`
  with reach 14.4 hangs, the stamp's pixels land in the ring or the verify band: (j) fails terminally.
  Correct: room 548 - 1.0 - 539.16 = 7.84, the unit is carried down. Same gap for growth over a
  stencil and for a stencil 0.3 pt outside the paragraph band (every edit fails (j)).
- Fix: drawings, images, image masks and shadings = every `get_bboxlog` entry whose code is NOT
  `fill-text`, `stroke-text` or `ignore-text` (closes the class); probe 8 gains an `/ImageMask`
  XObject and an inline `BI /IM true`, each also inside a Form.

### C15-1 (major, Codex): the fallback box is defined but not proven conservative
Plan 656-659 ("... never a failure") against 669-670 ("... can still fail (j) (terminal ...)"): the two
sentences contradict each other and R14-1 stays open for fallback glyphs.
- 10 pt neighbour, trace x [103,117], fallback [100.5,119.5], grown [99.5,120.5]; a planned glyph at
  [121,125]: the preflight passes with 0.5 pt of clearance; a neighbour painting through x = 122 is
  inside the planned glyph and its ring: (j) fails terminally.
- Opus R15-5 agrees on the threshold: ring contamination starts when the ink passes the fallback box
  by more than 0.5 pt (margin minus the 1 px ring), not "more than the margin".
- Fix: a bound that is proven to enclose the paint (transform and stroke expansion applied), or a
  refusal when it cannot be established; no exact-ink recovery needed. Remove "never a failure";
  add an overflow / refusal fixture.

### Minors (Opus unless noted)
- R15-2: at the clip edge the rasters disagree (UNVERIFIED mechanism: glyph-cache subpixel
  quantization): no margin applies to the clip and (j)'s reference is drawn unclipped. Clip right
  edge at M + 21, reach 21: up to 0.25 px of ink past the clip is clipped on the page and present in
  the reference. Fix: draw (j)'s reference through the body's effective clip.
- R15-3: (c) 747-748 "old and new line boxes AND glyph ink boxes": say old AND new ink boxes (a
  source glyph whose ink passes its old line box, then moved or deleted).
- R15-4: (e) "every glyph in the band" (753) now reaches foreign glyphs because the line box
  (hhea descender) widens the verify band: a 14 pt CJK last line just above a Latin line in another
  font overlaps its ink box by 0.6 pt. Fix: (e) selects by the replay join (glyphs of the rewritten
  bodies), not by position.
- R15-5 (Codex agrees in part): the stated limit understates the cost. Effective threshold = margin
  + pixel growth of the source box (0-0.5) + the neighbour's own growth when a glyph (0-0.5): about
  1.5 pt for drawings, up to 2.0 pt for glyphs. Likely casualties not named: Word table cells with
  zero top padding (0.6-1.8 pt, UNVERIFIED), underline / strike-through / highlight rectangles
  (always refused, correctly), CJK at an exact 1.0 em pitch. The S4 census records the first failing
  rule only: add a clearance histogram for `tier2r:source_ink_overlap` (passing at margin 0 vs 1.0)
  and a trigger for revisiting the margin.
- R15-6: `get_bboxlog` boxes ignore clips: a cropped image counts whole, an `sh` under a clip may be
  unbounded (UNVERIFIED), strokes may include the miter. Safe side (refusals). Probe 8 records box
  vs painted extent for a clipped `sh`, a cropped image, a mitred stroke; the census counts it.
- R15-7 (fixtures; Codex agrees on hairline and fallback): measure the 0.8 / 1.2 pt cases from the
  B.0 ink box right edge (pixel-grown); the S3 mark's reach must come from its ink (a `，` with ink
  right about 5 never reaches); a filled rect as the S4 neighbour; hairline: assert the numeric room
  and add an (i) case (planned ink crossing a 0-width stroked line is `tier2r:ink_collision`);
  fallback box pinned: 10 pt neighbour, trace x0 at M + 20, ragged mark with reach 17: room
  20 - 2.5 - 1.0 = 16.5 no hang (19 without the growth, 17.5 without the margin: both hang).
- Codex: whitespace foreign glyphs contribute an empty box (say so); 639 "above the floor": say
  whether equality fits.
- Nits: "shifted band" (536, 643) undefined; B.1 399-400 "no image, shading or drawing meets the
  band" should use the object-set boxes; define "planned glyphs" once (every glyph of the edited
  paragraph in the plan, kept lines and label included), else the (j) band sentence fails at tight
  leading; 688-689 "cannot fail on the same inputs"; section 23's "true ink gap >= 6.96" is the
  line-box gap (5.49 with P2c's char box).

## UNVERIFIED
MuPDF glyph-cache quantization; unbounded shading boxes; miter expansion; Word cell padding; `T`
and 2x antialiasing coverage (S0); whether the compiled extractor produces the fallback overflow case.

## Next
Revision 16: R15-1 (complement of the text codes), C15-1 (a proven bound or a refusal for fallback
glyphs), R15-2..R15-7, nits. Opus: a confirmation-only round 16 is enough. S0 only on CONVERGED
from both.
