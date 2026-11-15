# Paragraph grouping + original-font reflow: review round 17 (confirmation)

Date: 2026-11-15. Subject: `plans/paragraph-grouping-reflow.md` revision 17 (section 25) and probes P12/P13
(`plans/paragraph-grouping-reflow-probes/r16_probe_object_set.py`). Reviewers, independent: deep-reasoner
(Opus) and Codex (gpt-6.1-sol). Desk review; the reviewers ran nothing.

**Severity rule of this round (set by the designer in the review prompts, NOT an owner decision):** a
finding is major only if a plan can pass planning and then corrupt or wrongly change the document, change
a font, or fail verify terminally in a case that is not rare. A refusal with the document untouched, or a
terminal verify failure that needs a contrived neighbour, is minor ("stated limit candidate").

**Verdict: CONVERGED from both under that rule. No blocker, no major.** Whether this rule replaces the
earlier gate ("no major" without a rarity test) is the owner's decision; S0 has not started.

## Status of the round-16 findings

RESOLVED from both: R16-1 (a) whitespace by ink, R16-1 (b) / C16-1 fallback box by the span's own
`get_bboxlog()[seqno]` entry (no intersection, the assumption is gone), M2, M3, M5, the nits.
PARTLY: the class net (extent at its edges), M1 / evidence (probe wording), M4 (fixtures).

Both: every terminal (j) path found needs paint that NO extraction list reports (measured so far: a
tiling-pattern fill) lying in a strip a few pt wide around the paragraph. No route to a font change or
a wrongful commit. All fixture arithmetic is correct.

## Open findings (all minor)

- **m3 / Codex 1 (stated limit candidate): the net rectangle does not contain every planned ink box,
  its 1 px ring and the verify band**; plan 693-694 and 739-740 overclaim. Left: band left 72.00, a
  carried-down glyph with LSB -1.76 has ink x0 70.24, ring 69.74; an unlisted fill at [60, 71] passes
  preflight and net, (j) fails. Top: an inserted accented capital above the hhea ascender. Bottom: a
  growth line's line box ends at floor + 2.90, verify band floor + 3.40. Right: reach = `hang_room`
  puts the ring 0.5 pt outside; a D5 one-line paragraph has `hang_room` 0. Fix (one sentence): grow
  the net by 1 em left, top and right and below the floor by the largest hhea descender + 1 px
  (listed objects there are exempt boxes); reword the two claims. Not "planned boxes outside the net
  refuse" (that refuses ordinary growth lines).
- **m4 (erratum): B.1 (438) and C.4 (731) define different net rectangles** when the band's right
  edge passes M + `hang_room` (a source hanging mark to 552.00 with room 4.84). Net = bounding box of
  the band and [band left, M + `hang_room`] x [band top, floor], plus the shifted bands on the variant.
- **m5 (stated limit candidate): which boxes the net exempts on the shift variant.** Fix: boxes of
  glyphs whose bodies are emptied (edited and shifted paragraphs) are never exempt, at either position.
- **m6 (evidence + wording): the seqno identity check.** P12's page has no non-text device call before
  a text span, so seqno alignment across paths, clips, images, shadings, tiles is unmeasured; on a
  text-only page "is a text entry" is vacuous. Bounded: a wrong entry only enlarges the box or leaves
  paint to the net. Fix: one S0 (8) probe line with interleaved non-text calls and `Tr 3` / `Tr 7`;
  wording "absent, out of range or not a text entry; at admission; chain continues"; say whether
  `ignore-text` counts.
- **m1 (erratum): the crossable-hairline fixture can never give `tier2r:ink_collision`**: a line right
  of a short last line with x1 <= M is inside the band and is refused at admission. Replace with a
  vertical hairline at x 70.50 left of band left 72.00 (box grown to [69, 72], touches) and a
  carried-down word starting with a glyph of LSB -1.76; control: a word starting with `a` commits.
- **m2 (erratum): "does not hang" fixtures no longer separate a wrong implementation under the net**
  (the wrong code is refused at admission and "nothing hangs" is still true): each asserts the C.2
  `hang_room` value (10.5 / 1.4 / 7.84 / 18.5) or a Tier 2R commit with the unit carried down; the
  skew fixture's parenthetical is stale (trace-only is now refused by the net).
- **m7 (stated limit candidates): refusals the net adds or keeps.** Unlisted paint anywhere in the net
  (it reaches down to the next LISTED object or the CropBox bottom) refuses every edit of the
  paragraph, typo fixes included; a listed full-page underlay refuses every paragraph (older than
  revision 17, prevalence unknown: S4 census); a tiling fill's stray cell entry is a listed path at
  its pattern-space position. No wrong refusal from anti-aliased neighbour ink, a bound label, or an
  unlisted uniform background.
- **m8 / Codex 4 (erratum): fixture prerequisites.** S4 positive control: the rect 1.2 pt right of the
  band's right edge (advance end and ink edge); tiling fixtures: stray cell entry out of the bands, a
  listed floor object above the "below the floor" fill; `Tz 90`: the neighbour's own grown box clear
  of the source ink; shading: name a reach (14.04); the accent needs an embedded font (S0).
- **Codex 2-3 / N3-N4 (evidence wording): the plan again says more than the probe measured.** Section
  25 says item 1 "binds": P13 rendered only [M + 1, CropBox] over the source band, bodies not emptied,
  no floor, no object mask: write "no refusal found by P13; full net admission is S0". P12's `inside`
  allows 0.26 pt and samples within 45 pt of the trace union; P13 measures the span entry alone, not
  trace bbox united with entry, and filters the band with ungrown y-ranges; "7 of 7" is two faces
  (Helvetica, `china-t`), no embedded TrueType / CFF / Type3; no inline mask inside a Form.
- Nits: 1810 "at planning" vs 737 admission; (j)'s parenthetical (884-886) should cite the net; P13
  skips whitespace glyphs.

## UNVERIFIED (both)
Seqno alignment with non-text calls before text; `Tr 7` and pattern-filled text in either list; exact
glyph values of m1/m3 (the class is certain); how common full-page underlays are; the reference net
outside P13's strip; tricky TrueType faces in the glyph-id renderer.

## Recurrence
- This round: the collision net of C.4 / C.6 (object set and its render check): edges of the net rectangle, fixtures, probe wording.
- Previous round: the collision net of C.4 (object set can miss paint).
- Same mechanism: yes
- Class fix: applied in revision 17 (background net = a check on the rendered outcome instead of a longer object list); what is left is the net's extent (grow it by 1 em and the hhea descender) and probe lines for S0, not new object kinds. Rounds 12-16 patched instances of this class one by one; see the owner's question of 2026-11-15.

## Next
Owner decides the gate: accept the severity rule above (then S0 starts, with revision 17a = the sentence
edits m1-m8 and nits, no further round per both reviewers) or keep the earlier gate.
