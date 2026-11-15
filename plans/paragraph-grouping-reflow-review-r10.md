# Paragraph grouping + original-font reflow: review round 10 (narrow)

Date: 2026-11-15. Subject: `plans/paragraph-grouping-reflow.md` revision 10 (section 18 with its
addendum: the owner's hanging-punctuation rule). Reviewers, independent: deep-reasoner (Opus) and Codex
(gpt-6.1-sol). Scope: B.1 "Justification share" / "Hanging punctuation", C.2, C.3, C.6 (f)(g), S3-S5.
All counterexamples are desk arithmetic; nothing was executed.

**Verdict: NOT CONVERGED from both.** No blocker. Majors only in the hanging-punctuation text written
on 2026-11-15; the justification share of revision 10 held.

## Status of the round-9 findings

| r9 finding | Opus | Codex |
|---|---|---|
| F1 hanging punctuation | RESOLVED (replaced by the owner rule) | PARTLY (N1) |
| F2 condition (1) vs the reference | RESOLVED | PARTLY (N2) |
| F3 uneven widening | RESOLVED | RESOLVED |
| M-track / m1 tracking guard | RESOLVED | RESOLVED |
| m2, m3, m4, m5, m6, m8 | RESOLVED | RESOLVED |
| m7 | PARTLY (S3 wording) | PARTLY (S3 wording) |

Both confirm: candidate/share pair, baseline, `T0`, `widen`, `resid`, evidence line are deterministic and
non-circular; the r9 counterexamples (final glyph `Tc` 0, -0.7 pt kern, "a Year", 4 space pairs +3.0 with
one CJK pair +0) are all ragged; with M = largest body end no ordinary glyph passes M + 0.3 in the F1
cases; every line shape is well defined; `break_lines`, the range-start rule, convergence,
`unbreakable_overflow` and (g) 6 stay consistent.

## Open findings

### N1 (major, both): C.6 (f) still forbids what hanging produces
Plan (f): "no line's last non-whitespace atom has its advance end ... beyond the effective measure +
0.31 pt; every line whose C.3 share is above 0 ends within 0.31 pt of it."
- M = 539.2, a correct hanging `，` ends at 553.2 > 539.51: verify fails after the patch set exists,
  which is terminal (`tier2r_commit_failed`). Hits S3's own hanging cases.
- Fix: keep (f) independent of C.3 (fixed B.1 mark set, not `Hangs`): the end of the last
  non-whitespace atom, or of the atom before it when that atom is a hang mark, is <= M + 0.31, and the
  mark ends <= M + `hang_room`; a line with share > 0 has its end OR its body end within 0.31 of M.
  Add an S5 positive commit test with a hanging line; section 7 says "body ends at 539.2 +- 0.3".

### N2 (major, both; hits the reference): "flush" reads as body end only
Plan B.1 (2): "its end ..., or its body end when it ends in a hang mark ..., is within 0.3 pt of M".
- Item 1 line 2 ends in a mark INSIDE the margin: end 538.97, body end 524.9, 14.26 pt off M = 539.16:
  item 1 becomes ragged, section 7 fails; the plan's own notes compute "justified" from the ends.
- Fix: "either its end or its body end is within 0.3 pt of M". M stays independent of the classification.

### N3 (major, Codex): `hang_room` ignores the effective clip
- M = 539.2, CropBox right 600, no objects, clip right 545, 14 pt mark: `hang_room` 60.8, planning
  admits a mark ending 553.2, (i) fails terminally.
- Opus read the C.4 clip rule as a planning-time refusal (`clip_too_tight`), so the outcome would be a
  refusal, not a terminal failure. Either way the mark should be carried down instead: bound
  `hang_room` by every applicable effective clip.

### N4 (major IF a producer hangs two marks; unmeasured; Opus): the source body strips one mark only
- Lines 567.3 (`。」`, both hanging; ideograph ends 539.2) / 539.2 / 300: body end 553.2, M = 553.2,
  ragged; an ideograph typed on line 2 lies in 539.2..553.24; (g) 7 and the fixed (f) accept it.
- Fix: when reading the SOURCE the body drops its whole trailing run of hang marks; flush accepts the
  end of the body or of any atom in that run. Layout still hangs one mark. Add to the S0 census.

### Minors
- N5 (Opus): `hang_room` omits Form XObjects (C.4's list has them; the reference page has Fm1..Fm10)
  and the shift-variant band; (g) 6 needs `hang_room` too. Use C.4's object list, extend the band to the
  lowest planned line, say in (g) 6 and (g) 7 that it is recomputed from the source page pass.
- N6 (Opus): `。」` when neither mark fits carries `字。」` down, against "the character before it is NOT
  carried down". Conservative; state it as a designed exception.
- N7 (Opus): cost of the stated limit: when every line ends in a mark inside the margin, a justified
  line whose total widening is >= one mark + 0.3 pt no longer hangs when re-laid unchanged and shrinks
  about 14 pt toward M. Two-line paragraphs whose line 1 ends in `，` at the margin hit it. Census.
- N8 (both): S3 still says "a justified line with no opportunity".
- N9 (Codex): even spread takes a minimum over an empty set on a line without share pairs (define it as
  satisfied); "font size of most atoms" has no tie rule.

## Reference item 1 under revision 10 (Opus, P2b numbers, with N2 fixed)
`base(cjk)` 0 from 11 pairs; line 1 `share_src` 0, re-laid: slack 0, `d` 0, bytes verbatim; line 2
`share_src` 0.208, `resid` 0.112 (evidence), re-laid unchanged: share 0.217, end 0.19 pt further right.

## Next
Revision 11: N1-N4 and the minors (all inside B.1 "Hanging punctuation", C.2 `hang_room`, C.6 (f),
S3/S5); then narrow round 11 on the hanging rule only. S0 only on CONVERGED.
