# Review round 5 of `paragraph-grouping-reflow.md` revision 5 (2026-11-14): NOT CONVERGED

Record for writing revision 6 without the transcripts. R = deep-reasoner (Opus; reviewed all of sections
4-6): 0 blockers, 1 major (F1), 7 minors (F2-F8). X = Codex `gpt-6.1-sol` (reviewed N1-N6 and regressions):
0 blockers, 2 majors, 1 minor. Both reviewers' majors are ONE rule: check C.6 (g) 6. Nothing is implemented.

## What both accept

- Donor transaction (C.7, D): RESOLVED from both. R tried commit / undo / redo with save over the open
  file, `garbage>=2`, `garbage=4` merges (donor, sibling faces, `/Properties`), Tier 0 and Tier 2R commands
  on either side, system and in-document donors, inherited / direct / indirect `/Resources`: every sequence
  ends proven, STALE with the start state restored, or relocated through the content invariant.
- All rows of section 12 except "pull-up"; N1, N2, N3, N4, N6 of section 13. N1: removing the equal-layout
  early return admits only a re-pointed name, a merged equal object or a renumbering; merged OCGs with
  different visibility are still refused (`inspect.py:954-956`).

## Open findings

### Major: C.6 (g) 6 "every soft break is required" (R F1, X 1, X 2; N5 PARTLY)
1. False pass on justified lines: the next word is placed after the replayed last atom, which on a
   justified line already ends at the measure. A plan that keeps the old breaks after a deletion and
   re-justifies (slack under the 0.5 em cap) passes (f), (g) 5 and (g) 6. The S5 control would pass on the
   reference shape.
2. False failure from the word definition: (g) 6 uses the A.1 first word, but B.1 has no break opportunity
   at a CJK to Latin/digit boundary, so `2026年11月14日` is one unit for the breaker and `2026` for A.1.
3. False failure under C.8: (g) 6 says "the source measure"; after the right edge is dragged every correct
   re-wrap fails.
Change: take each line at its NATURAL end (replayed advance end minus the line's justification expansion,
derived independently: replayed width - sum of natural advances - sum of intrinsic lead-ins, not the
planner's declared share); place the next line's first unbreakable unit (B.1 opportunities + C.3 kinsoku
binding + hanging whitespace, the break before a converged line included) against the C.2 measure (the
C.8 frame when dragged; anchors use the same effective geometry). Put the S5 control on a JUSTIFIED line.

### Minors
- F2, C.6 (a) vs number format: 2-decimal kerns err the same way along a run (up to 7e-5 pt each at 14.04
  pt); 15+ kerns exceed 0.001 pt and a correct emission fails (a). Change: planned origins in (a) are
  derived from the emitted, rounded operands; add a re-justified line to S0 probe 2.
- F3, C.6 (g) 5: pairs with inserted atoms or joined across a former line break are checked against
  nothing independent. Change: (g) 5 checks EVERY adjacent pair against the C.1 lead-in rule (body `Tc`,
  `opp_cjk`/`Tc` at joins) plus the share delta, 0.01 pt.
- F4, C.1/C.3: deleting a newline `join_sep` is "an ordinary edit" but the re-break never crosses a hard
  break, so the deletion is silently lost. Change: v1 refuses an edit that inserts or deletes a newline
  (`tier2r:hard_break_edit`).
- F5, S6a N1 test: `garbage>=3` compacts the table; unless the duplicate `/Properties` objects have the
  highest numbers the layout changes and today's code already relocates (test green before the change).
  Change: state the fixture constraint and assert the layout tuple is equal before undo A.
- F6, slices: "a one-line Tier 0 session that overflows gets a Tier 2R token" needs growth, S5 is "no
  growth". Change: move the test to S7 (or move grow-down into S5).
- F7, C.0: only the token path calls a verify failure terminal; on the tokenless path a Tier 2R plan or
  verify failure after admission can reach the consented rebuild (`pdf_text_edit.py:5063-5068`), where the
  font jumps. Change: one sentence: after admission, a Tier 2R plan or verify failure is terminal.
- F8, C.7 record path: say that it does today's bookkeeping too (exact stream storage, protection
  membership, MaintenanceBook, page index rebuild; `edit_commands.py:856-861, 930-937`).
- X minor: the token preimage list in C.7 must name `style_overrides` (C.0 already says so); "refuses every
  foreign change" in C.7 should read "every change the invariant covers" (`inspect.py:990-1004`).

## Handoff

Revision 6 = the (g) 6 rule above plus one-line fixes for F2-F8 and the X minor; no change to the donor
transaction. Add a "round 5 -> revision 6" table. Round 6 can be narrow (both reviewers: (g) 6 and the
touched sentences). S0 only when both say CONVERGED.
