# Paragraph grouping + original-font reflow: review round 9 (narrow)

Date: 2026-11-14. Subject: `plans/paragraph-grouping-reflow.md` revision 9 (section 17).
Reviewers, independent: deep-reasoner (Opus) and Codex (gpt-6.1-sol). Scope: B.1, C.0, C.2, C.3,
C.5 "Inside a run", C.6 (f)(g), slices S3-S5. All counterexamples are desk arithmetic; nothing was executed.

**Verdict: NOT CONVERGED from both.** No blocker. Three majors (one conditional on an unmeasured fact).

## Status of the round-8 findings

| r8 finding | Opus | Codex |
|---|---|---|
| C1 (blocker) `inferred_ws` in the share | RESOLVED | RESOLVED |
| C2 / X2 tracking taken for justification | PARTLY (F3, m1, m2) | PARTLY (M-track) |
| D2 hanging punctuation | PARTLY (F1) | PARTLY (M-hang) |
| X1 / A1 kept lines vs (g) 1 | RESOLVED | RESOLVED |
| B1, E2, D3, X minor 3, m2 nit, m5, C.0 note, wording | RESOLVED | RESOLVED |
| E1 | RESOLVED (m6) | RESOLVED |

Both confirm: the share definition is deterministic and non-circular; C.3, C.5 `d` and (g) 5 use share
pairs consistently; every line has exactly one anchor/origin check; no path changes the font without
consent and no mutation is left behind before a patch set.

## Open findings

### F1 (major, both reviewers): hanging punctuation is refused only for ONE widest line
Plan: "the largest line end belongs to exactly ONE line ... next-largest end among the other non-last lines".
- (a) Two lines hang: ends 553.2 (`，`) / 539.2 / 553.2 (`。`) / 539.2 / 300 (Opus), or 553.2 / 553.2 / 300
  (Codex). Not refused; measure 553.2; an inserted ideograph lies in 539.2..553.2; verify accepts.
- (b) One non-last line: ends 553.2 (`，`) / 300. There is no "other non-last line", never refused.
- Fix (Opus): R = largest end among non-last lines whose last content atom is NOT no-line-start
  punctuation; with none, A.1's column measure computed over such lines only (carried in the bind
  target). Refuse when a punctuation-ended line ends beyond R + 0.3 while its end without that atom is
  within R + 0.3. With no R at all, refuse unless >= 2 non-last lines all end in such punctuation and
  agree within 0.3. Reference items 1 and 2 stay admitted.

### F2 (major IF the fact holds; unverified; revision-9 regression): condition (1) vs the reference
Plan: "every class that occurs on a non-last line has a baseline".
- P2 records four real space glyphs in items 1/2 but not their lines. A body space on lines 1-2 and none
  on line 3 makes item 1 ragged, and section 7 (justified lines end at 539.2 +- 0.3) fails.
- Fix: S0 records item 1's share pairs per line and class. Replace (1) with, inside the share-pair
  definition: a pair whose class has no baseline is not a share pair and keeps its source lead-in. A
  materialized join space is a share pair only when `base(space)` exists.

### F3 (major, Opus; producer premise unmeasured): one mean over unevenly widened pairs
- 12 pt justified line, 4 space pairs widened +3.0, one CJK pair widened +0: `share_src` 2.4, intrinsic
  lead-in of the CJK pair -2.4. Moved to a last line (share 0) the two glyphs overlap; (g) 5 expects
  exactly that gap and passes.
- Fix: condition (6): on every non-last line, min over share pairs of (lead-in - base) >=
  `share_src` - 0.05 em, else ragged. Reference: min 0 vs mean <= 0.46 pt, bound -0.70 pt, admitted.

### M-track (major, Codex) = m1 (minor, Opus): the uniform-tracking guard (5) is bypassed
Plan: "every atom of the non-last lines has one `Tc` T1".
- X2 shape (ends 109/109/30) with the FINAL glyph of each non-last line at `Tc` 0: geometry unchanged,
  (5) fails, paragraph is justified, a deletion stretches ten glyphs to 109 instead of 108.
- Also: one -0.7 pt kern on line 1 gives `share_src` 0.919, |0.919 - 1| > 0.02; a space in its own show
  at another `Tc`.
- Fix: test the `Tc` of the LEFT atoms of share pairs (Tc is added after a glyph), not every atom; use
  the median, not the mean.
- Severity taken as major (the stricter reading; wrong layout that verify accepts).

### Minors (Opus)
- m2: a baseline from a single pair (2-line ragged Latin, last line "a Year" with the space kerned -0.6)
  makes the paragraph justified. Require >= 3 pairs per class for a baseline.
- m3: (g) 1 omits C.2's anchor for lines beyond the source count.
- m4: the median of an even count is undefined.
- m5: C.0 says outcomes are "classified by CODE, not by phase" while `internal_error` is defined by
  phase; C.7 "Scratch rendering" does not say the restore runs on an exception (worst case
  `PREVIEW_STALE`). Add a finally clause and an S5 preview-path test.
- m6: an emptied E that is the first line of its segment has no previous line there; the range starts at E.
- m7: S3 "with no opportunity" -> "with no share pair"; add F1 (a)(b) to the S4 tests.
- m8: ragged 553.2 (`，`, 539.2 without it) / 545 is refused today; conservative; census only.

## Codex desk-runs that held
(a) X2 as recorded: ragged, 108/20 after the deletion. (b) X1: starts 104.66 / 104.86 kept, (g) 4 only.
(c) kern-made Latin: ragged, gaps 3.6 / 3.5 / 3.33 kept. (d) tracked ragged Latin: share 0.
(e) 539.2 / 553.2 / 300: refused. (f) reference: justified, line 2 targets 539.2, last line unstretched.

## Next
Revision 10: F1, F2 (needs the S0 measurement of item 1's share pairs per line), F3, M-track, minors;
then narrow round 10 on B.1 "Justification share" and "Hanging punctuation". S0 only on CONVERGED.
