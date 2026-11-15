# Paragraph grouping + original-font reflow: review round 11 (narrow)

Date: 2026-11-15. Subject: `plans/paragraph-grouping-reflow.md` revision 11 (section 19). Reviewers,
independent: deep-reasoner (Opus) and Codex (gpt-6.1-sol). Scope: the hanging-punctuation rule only
(B.1 "Hanging punctuation" and justified conditions (2)/(4), C.2 `hang_room`, C.3 "Hangs"/"Fits"/"Share",
C.6 (f), (g) 6-7, (i), S3-S5). All counterexamples are desk arithmetic; nothing was executed.

**Verdict: split. Opus CONVERGED (no blocker, no major, 7 minors). Codex NOT CONVERGED (one major).**
So the plan is NOT CONVERGED; S0 does not start.

## Status of the round-10 findings

N1-N9: RESOLVED from both reviewers (Opus notes the census part of N4/N7 as m2 and the wording of N5 as m6).

Both confirm: every line shape is defined and deterministic (mark as only atom, runs of two or three
marks, content of marks only, mark + trailing whitespace, mark before a hard break, last line, lines
beyond the source count, frame change, one-line paragraph, shift variant); `hang_room` is not circular
(source page pass, effective geometry, variant only); no ordinary glyph passes M + 0.3 and is accepted;
legal hanging plans pass (f) and (g) 7; the flush OR cannot make a ragged paragraph justified (condition
(3) still needs evidence lines; Codex: ends 540 (`，`) / 500 / 525 (`。`) / 300 -> M 526, ragged).

## Open findings

### R11-1 (major, Codex): advance clearance does not guarantee ink clearance
Plan: Hangs requires "`ilead`(mark) + advance(mark) + 0.5 em <= `hang_room`"; (i) requires that ink meets
"no glyph ink of another paragraph, drawing, image or annotation".
- M = 539.2, 14 pt mark, `hang_room` 22 (another paragraph's glyph begins at 561.2). Hangs passes
  (14 + 7 <= 22), (f) and (g) 7 pass. A mark whose ink reaches 9 pt past its advance (562.2) overlaps
  that glyph; C.4's precheck covers clips only; (i) fails terminally. A legal plan rejected by verify.
- Fix: before any patch set, preflight the planned ink of a hanging mark against (i)'s collision
  constraints; on a hit the mark does not hang (carry-down exception) and the layout is redone. Keep the
  advance-based `hang_room` deterministic; add an overhanging-ink positive/control case.
- Opus did not raise it; its m4 (c) is the same class (a terminal (i) failure through `hang_room`).

### Minors (Opus)
- m1: a producer that CARRIES marks instead of hanging them. Justified, M 539.2, line 1 natural end
  519.2, line 2 starts with `字，`: a typo fix in the middle of line 2 moves the range start to line 1,
  line 1 takes `字` and hangs `，`, the segment re-flows. Section 18 says "the owner's rule wins" while S0
  probe (7) says "if not, revise C.3". State it as limit (c); probe (7) records it; census.
- m2: the limit (a) census criterion misses 2-line items (line 1 ends in `，` at the margin, the last
  line in an ideograph): count paragraphs whose every NON-LAST line ends in a mark; also count
  two-mark hanging runs.
- m3: "+0.5 em" reserves too much: ragged, M 575, CropBox 595.3, source `，` hanging to 589:
  `hang_room` 20.3 < 21.06, the unchanged line is re-laid with `字，` carried down. Reserve 0.5 em only
  when the paragraph is justified and the mark pair is a share pair; else 0.3 pt.
- m4: `hang_room` geometry underspecified: (a) objects left of or straddling M; (b) item 2's top touches
  the band at the floor: closed intervals would give `hang_room` <= 0; (c) "from the paragraph's first
  line" read as the first baseline misses an annotation beside line 1's ascender zone -> terminal (i)
  failure. Count only objects with x1 > M at distance max(0, x0 - M), ink boxes; band from the top of
  the first line's box, open at the floor.
- m5: "closing brackets" is an open-ended set; if (f)'s set and C.3's differ (`”`), a legal hang fails
  (f) terminally. One named constant with its code points, used by B.1/C.3 and (f).
- m6: (f) says it "does not call C.3" but uses the C.3 share; (f) uses `hang_room` but C.2 names only
  planning and (g); (g) 7 lacks the +0.01 that (f) has. Name (f) as a caller, take the share from
  (g) 5's computation, align tolerances.
- m7: the em of "Hangs" is not named; say "the line's em (C.3 Share)".

## Reference item 1 (P2b numbers; both reviewers)
M = 539.16; line 2 flush by its mark end 538.97; justified. Typo fix on line 2: natural end 534.39,
share 4.77 / 22 = 0.217, e = 539.16, (f) and (g) 7 pass. One ideograph inserted on line 2: body ends
about 534.5, `，` hangs when `hang_room` >= about 20.9 (the reference's `hang_room` is UNVERIFIED: CropBox,
Fm1..Fm10 and item 2's right extent are not in the plan); otherwise `字，` moves to line 3 and the
paragraph stays at three lines.

## Next
Revision 12: R11-1 (ink preflight for the hanging mark) and m1-m7 (wording, limits, census); measure the
reference's `hang_room`. Then a narrow round 12 on `hang_room` / "Hangs" / (f) / (i). S0 only on CONVERGED
from both.
