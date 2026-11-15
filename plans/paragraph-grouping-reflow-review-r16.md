# Paragraph grouping + original-font reflow: review round 16 (narrow)

Date: 2026-11-15. Subject: `plans/paragraph-grouping-reflow.md` revision 16 (section 24) and the object-set
probes P10/P11 (`plans/paragraph-grouping-reflow-probes/r15_probe_object_set.py`). Reviewers, independent:
deep-reasoner (Opus) and Codex (gpt-6.1-sol). Scope: the C.4 object set as rewritten from the
measurements, its consumers, the fixtures. Desk review; the reviewers ran nothing.

**Verdict: NOT CONVERGED from both. No blocker. One major each, the same class: paint the object set
can miss, so a plan that passes the preflight can fail (j) terminally (document untouched).**

## Status of the round-15 findings

RESOLVED from both: R15-1 (image masks), R15-2 (clip edge), R15-3 (old ink boxes), R15-4 ((e) by the
replay join), floor equality, shifted band, uniform-background rule, planned glyphs, "cannot fail on the
same inputs". PARTLY: C15-1 (both), R15-5 (Opus, M3), R15-6 and R15-7 (Codex), whitespace box (Opus).
OPEN: the section-23 "true ink gap >= 6.96" nit.

Both confirm: the non-text definition is consistent across C.2, the floor, the preflight, (i), the
admission self-check and the uniform-background rule; no failure of (c), (e) or (i) found; no new
contradiction in (f), (g) 7 or the hanging rule; no double counting of joined fill-only neighbours.

## Open findings

### R16-1 / C16-1 (major, both): the fallback box and the whitespace rule can leave paint out
Plan 671-685: "nothing is ever left out"; "A whitespace glyph has no box"; "every `get_bboxlog` TEXT entry
that intersects that bbox"; "Stated assumption: a glyph's paint meets its own trace bbox".
- Codex (abstract): the assumption is a condition, not a bound. Trace box [100,110], paint [115,120],
  entry [114,121]: no intersection, the fallback stays the trace box, a planned glyph at [116,118]
  passes the preflight and meets the paint. Whether the extractor produces this: UNVERIFIED.
- Opus (a): whitespace is decided by Unicode. A neighbour glyph with ink whose ToUnicode maps it to
  U+0020, ink at [M+11.5, M+20]: no box, `hang_room` 56.40, a `，` (reach 14.04) hangs, its line box
  covers the ink in [M+11.5, M+14.04]: (j) fails. Correct: room 10.5, the unit is carried down.
- Opus (b): a zero-advance glyph has a zero-width trace bbox (reference device: x1 = x0 + advance;
  compiled device UNVERIFIED) and can never "meet" (> 0.01 pt on both axes) its own entry. A
  Form-painted lone U+0301, origin M+6, ink [M+2.4, M+5.4]: fallback = degenerate box, room 5.0, a `”`
  (reach 4.4) hangs over the accent's ink: (j) fails. Correct: room 1.4.
- Fix (Opus, two sentences): a foreign glyph has no box only when its B.0 ink box is empty, and a
  fallback glyph is never dropped; a fallback glyph takes in its OWN text entry, `get_bboxlog()[span
  seqno]` (verified for the reference devices, UNVERIFIED for the compiled texttrace: make it a P10
  assertion; else "every entry that meets its trace bbox widened by 1 em"). Codex: make the guarantee
  conditional and refuse when a conservative bound cannot be established.
- **Class net** (Opus, optional, one sentence): run the B.1 uniform-background render over the
  rectangle from the band's left edge to M + `hang_room` and from the band top to the C.4 floor, with
  the paragraph's bodies emptied (shifted bodies too on the variant). That rectangle holds no object
  box by construction, so a second colour there is paint the set missed:
  `tier2r:band_background_not_uniform` at planning. Every leftover miss becomes a refusal.

### Minors
- M2 (both): a fallback glyph's union takes in other shows' entries, the edited paragraph's own
  included -> wrong `tier2r:source_ink_overlap` (Codex: edited entry [100,150] x [100,110], foreign
  trace [140,160] x [109,125]; Opus: a `Tz 90` run on the next line at pitch 11.5). The seqno
  sentence removes it; else exclude entries inside a body of the paragraph under test.
- M1 (both): P11 does not measure the revision-16 object set. probe9 compares rawdict char boxes
  across extraction blocks; item 1 lines 2-3 and item 2 share a block, so item 1 vs item 2 was not
  measured (6.96 = 21.0 - 14.04, line 1 vs line 2 of the same paragraph). The fallback boxes of the
  3 `stroke-text` shows and the Form text (Fm1..Fm10) against item 1's band are unmeasured; P10's
  stroke entry is about 10 x the pen width per side. "The margin refuses nothing on the reference
  page" (178, 703, 1739) is not established.
- Evidence (Codex): section 2 reports shading variants (no `/Extend`, `/BBox`, nested and triangle
  clips) and a header example that the committed probe does not build (they were measured with an
  uncommitted scratch script); `probe8()` prints boxes without asserting enclosure, and its ink
  threshold (grey 250) is looser than (j)'s "differs from the background". No inline mask inside
  the Form. Five text cases of one base-14 font (Opus) vary transform and render mode only.
- M3 (Opus): the stated limit (1.5 / 2.0 pt) understates the cost. The B.1 band is spanned by hhea
  line boxes: Calibri 12 pt, a 0.5 pt rule 3.8 pt below a line without descenders (ink clearance
  3.05): the grown rule (b+2.55) meets the line box (b+3.0): refused. Fallback and synthetic-bold
  neighbours count from coarse boxes. Say so; census by kind.
- M4 fixtures (both): the S4 control "1.2 pt away binds" must be right of the line's last advance
  end; the hairline at M+20 can never be crossed (name a second one); "cut by its clip edge" needs
  the case where the cached ink box under-covers the render; ink right - advance >= 0.3; name the
  reaches; the shading fixture needs a clip beyond M + 1 pt and outside the band; the skew fixture
  needs its intervals (trace right 174.46, paint 178.25, entry 179.35, planned [176.46, 177.46]).
- M5 (Opus): the 348 vs 326 gap is an asymmetric predicate (`isspace()` vs three code points) plus
  possibly Tr 2 twins, MediaBox clipping, Form text. Over-counting is safe. One probe line with the
  same predicate and counts per span type.
- Nits: "intersects" vs "meets" (not `Rect.intersects`, False for empty/infinite rects); an entry is
  one device call, possibly a multi-show body; "the floor of the shifted band" (554-555) undefined;
  1725 still open.

## UNVERIFIED (both)
The compiled texttrace device (seqno = bboxlog index; char bbox = advance box); tiling patterns
(PatternType 1: the bbox device has no `begin_tile`) and shading-pattern `scn` fills; tricky TrueType
faces (bound vs hinted render); the stroke shows and Form text beside item 1; MuPDF's text flush
granularity; how common tight table cells and full-page underlays are.

## Next
Revision 17: the two R16-1 sentences; the class net (designer recommends adopting it: it ends the
enumeration of object kinds); probe: fold the scratch shading cases in, assert enclosure with (j)'s
threshold, add tiling pattern, shading pattern, zero-advance glyph, a CJK font, the reference Form
text, and measure the reference with the revision-16 boxes; M1-M5 wording. Then a confirmation round.
