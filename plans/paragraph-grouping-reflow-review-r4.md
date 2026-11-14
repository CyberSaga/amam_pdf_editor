# Review round 4 of `paragraph-grouping-reflow.md` revision 4 (2026-11-14): NOT CONVERGED

Record for writing revision 5 without the transcripts. X = Codex `gpt-6.1-sol` (read-only): no blocker, 5
majors, 1 minor (N1-N6). The deep-reasoner (Opus) review did NOT finish: it stopped on the account's usage
limit and returned no report, so round 4 has ONE reviewer. Nothing is implemented.

## Owner guidance (2026-11-14, after the Codex result)

"Whether an edit goes through Tier 0 or Tier 2R is not the point. Focus on the goal: the font must not
jump." Reading (designer's): tier order is an implementation detail the owner does not rule on; a change
is judged by whether unedited and inserted text keep the original face. Revision 5 must not add mechanism
whose only purpose is tier ordering, and every finding below is to be resolved by the smallest rule that
keeps the font, a stated refusal included.

## Rows of section 12 (X)

RESOLVED: X1/M1, X2, X3/M2, m1-m3 (the donor transaction: both round-3 blockers), X4/m6, M4, M6, m8,
X10/m4, X7/M8, m11/m12, X8, X9, M7/m9, system donors in v1.
PARTLY: X5/M3 (N2), X6/M5 (N5), X11/m10 (N6), pull-up (N5).

## Open findings

- **N1 major, C.7 stream-only reversal beside a donor command.** `_relocate` refuses when the recorded
  layout is unchanged (`edit_commands.py:703`); the layout holds page, streams, fonts and annotations
  (`:656`) but not `/Properties`, whose reference numbers enter `page_fingerprint`
  (`marked_content.py:523`). Tier 0 command A, donor command B, undo B, `garbage=4` serialization that
  merges two identical `/Properties` objects: A's fingerprint fails, the layout is equal, relocation
  refuses, A is STALE although the page content is A's. (This exists today without Tier 2R; the donor
  path makes it more likely.) Change: after a fingerprint failure a retained stream reversal attempts
  the content-proved relocation even when the layout is unchanged; add the sequence to S6a.
- **N2 major, C.5 verbatim run origin.** The condition "starts at its source show's first glyph, unmoved
  line, unchanged share" also holds for a show AFTER an insertion on the same ragged line, whose x has
  moved; copying the source `Tm` puts it back and check (a) refuses a valid edit. Change: verbatim only
  when the planned first-glyph origin equals the source origin, and the copied operands are the ones that
  set that show's origin.
- **N3 major, B.0 consecutive shows.** `Tm [(AB)]TJ [(CD)]TJ` in one body is admitted, but the replay does
  not advance `tm` between shows (`replay.py:564-586`) and `predict_glyphs` starts each show at 0
  (`glyph_boxes.py:361`), so CD is predicted at AB's origin and the join fails. Change: either the page
  pass continues the cursor across shows with predicted advances (reset on `Tm`), tested in S1, or v1
  admits only bodies in which every show follows its own `Tm` (the reference shape; smaller).
- **N4 major, C.0/C.7 explicit restyle.** Requests carry `style_overrides` (`preview.py:80`); Tier 0
  refuses changed overrides (`plan.py:1889`, `pdf_text_edit.py:4733`). Tier 2R runs first, keeps the
  source paint and its token omits the overrides: a "make it red" request is silently dropped. Change:
  a request with a changed style override is a `tier2r:restyle_requested` admission refusal in preview
  and in live planning; overrides enter the token preimage.
- **N5 major, C.3/C.6 pull-up.** (1) Convergence "same first atom, same baseline, same x" is already true
  for a line edited in its middle. (2) Nothing verifies that pull-up happened: keeping every old break
  after a shortening edit passes (a)-(m). Change: convergence is tested only for lines that start after
  the changed span and requires the whole line state to equal the source line; add a check that for every
  soft break of the re-broken range the first word of the next line does not fit (or kinsoku forbids
  it), computed from replayed positions and the measure.
- **N6 minor, section 6.** "Line pitch after a donor edit" is in S6a, the line-pitch API is S8: move the
  assertion to S8.

## Handoff

1. Revision 5: N1-N6 as above (N3 by the narrower admission unless the S1 census shows consecutive shows
   are common), plus the owner guidance. Add a "round 4 -> revision 5" table.
2. Round 5 with BOTH reviewers; the Opus half of round 4 is owed (it was cut by the usage limit, not
   answered). S0 only when both say CONVERGED.
