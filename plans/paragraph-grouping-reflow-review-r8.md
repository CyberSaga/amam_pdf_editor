# Review round 8 (narrow) of `paragraph-grouping-reflow.md` revision 8 (2026-11-14): NOT CONVERGED

Record for writing revision 9 without the transcripts. R = deep-reasoner (Opus): 1 blocker (C1), 2 majors
(C2, D2), minors. X = Codex `gpt-6.1-sol`: 2 majors (X1, X2), 2 minors. Nothing is implemented.

## What both accept

- r7 A (laid-out vs kept lines), D (measure = largest line end), E (range start, frame change), F
  (`share_src` without opportunities) and m2-m7: RESOLVED (m5 partly: C.7 Commit still says "return the
  refusal"; name `tier2r_commit_failed`). "One step back is enough" was checked on five edits; (g) 6
  recomputes the planner's range start. Left anchoring (B) gives the right outcome for every listed
  shape; the column clause is order-independent. No regression in the donor transaction or section D.
  X's four round-7 counterexamples now come out right.

## Open findings

- **C1 (R, BLOCKER) `inferred_ws` pairs enter the share.** B.1 makes an `inferred_ws` pair an opportunity
  and subtracts `share_src` from every opportunity lead-in, with the baseline taken from CJK/CJK pairs
  ("0 when they hold no such pair"). When word spaces are `TJ` kerns (probe P2: such gaps are `synthetic`
  -> `inferred_ws`; S2 fixture `[(Hello) -500 (world)]TJ`), `share_src` is the whole word gap: the
  paragraph is "justified", the intrinsic word gaps are about 0, a typo fix pulls a word up and lays the
  line out with words glued or overlapping; (d), (f), (g) 5/6 and (j) all pass and extraction may lose
  the spaces. The reference file is not affected (no synthetic spaces in items 1/2). Change: separate
  "break opportunity" from "share pair". Share pairs = CJK/CJK pairs and pairs after a whitespace ATOM.
  `inferred_ws` and `join_sep` pairs never enter `share_src`, the justified test, the C.3 share
  denominator, the gap share or C.5 d; their intrinsic lead-in is the source lead-in. A paragraph with
  no share pair is ragged.
- **C2 (R major; X2 major) tracking is taken for justification.** The baseline for after-space pairs is
  the CJK median or 0. (i) Ragged Latin tracked with `Tc` 0.5: `share_src` 0.5 -> justified -> gaps grow
  from 0.5 to about 4.8 pt after a deletion. (ii) CJK on a grid whose last line has no CJK/CJK pair:
  baseline 0, the grid pitch counts as widening. (iii) X2: ragged CJK, lines 1-2 with `Tc` 1 and the last
  line with `Tc` 0 (ends 109/109/30): declared justified; a deletion stretches line 1 to 109 instead of
  98. (iv) "compressed gaps stay in the intrinsic lead-in" is false when `share_src` < 0: a laid-out
  line then exceeds the available width and sheds units. Change: baseline = median lead-in over the
  SHARE pairs of the segments' last lines, per pair class; none -> the paragraph is ragged (no 0
  fallback); clamp `share_src` = max(0, ...); X2 asks for more: positive expansion must be shown after
  subtracting independently established intrinsic tracking (for example the `Tc` in effect / the same
  show's own tracking), and an uncertain decomposition is ragged. Item 1 is not affected (line 3 holds
  CJK pairs).
- **D2 (R major) hanging punctuation defines the measure.** zh-TW Word may let a line-end `，。` hang past
  the margin (default unverified). Ends 539.2 / 553.2 / 300: non-last ends disagree -> ragged, measure
  553.2; an insertion on line 1 fills to 553.2 (ideographs 1 em into the margin, justification lost);
  (f) passes. Change: refuse `tier2r:hanging_punctuation` when the largest end belongs to a single line
  whose last content atom is no-line-start punctuation and the next-largest non-last end (or A.1's
  column measure) is more than 0.3 pt smaller; count in the S4 census. Item 1 (539.2 / 539.0) is not
  affected.
- **X1 (X major; R minor A1) kept lines vs (g) 1.** B.1 admits continuation starts within 0.3 pt, kept
  atoms keep their source origins, but (g) 1 requires every line at the one anchor within 0.01 pt: a
  kept line 0.02-0.3 pt off fails verify terminally on every edit (X: continuation starts 104.66 /
  104.86 on the reference shape). Change: (g) 1 and (g) 2 apply to laid-out lines only; kept lines are
  checked by (g) 4 alone, with the 0.001 pt tolerance of (a) (a recomputed `Tm` y is rounded). (f) says
  "from the replay alone" but needs the laid-out/kept split of (g) 6.

## Minors

- B1: start(F) for a labelled line (label x0 or body x0) is undefined in the competing-evidence test;
  "admitted" in the column clause should read "proven left-anchored by the n >= 2 clause"; the bind
  target DTO must carry the neighbouring paragraphs' line starts (`bind_paragraph` sees one target).
- E1: "E's new first unit" is undefined when E loses every atom (whole last line deleted: E-1 stays a
  kept, stretched line as the new last line). Change: when E is left empty the range starts at E-1.
- E2 (R; X minor 4): "an effective anchor x differs" also matches a horizontal move, against "a pure move
  re-breaks nothing". Change: trigger on a changed AVAILABLE WIDTH; pure translation has precedence; a
  move plus a text edit uses the ordinary range on the translated geometry.
- D3: in a ragged paragraph the widest line wraps on any growth even when the column has room: state it
  as a limit, or use A.1's column measure when one exists.
- X minor 3: S3 still says "a ragged paragraph and a two-line paragraph never justified" and also "a
  two-line paragraph with widened gaps: justified". Delete "and a two-line paragraph" from the former.
- m2 nit: add `inferred_ws` to the masks listed in the (g) header.
- C.0 (2) note (owner's call): a deterministic exception before the patch set makes the paragraph
  uneditable although Tier 0/1 could edit it in the same font.
- Wording: the heading at line 3 still says "design revision 7"; section 3 ("D5 inherited for the
  breaker") contradicts C.2; "E changes baselines only" uses E for section E while E also names the
  edited line.

## Handoff

Revision 9: ONE definition for C1 + C2 (share pairs; last-line baseline per pair class, ragged when
absent; clamp; expansion shown beyond tracking), the D2 refusal, (g) 1/2 on laid-out lines only, and the
one-line minors; nothing else. Then a narrow round 9 on B.1 and C.3 / C.6 (f)(g) only. Pattern of rounds
7-8: every remaining finding is about telling justification from the producer's own spacing; the safe
direction is the same as for anchoring: classify as ragged (share 0) on doubt. S0 only when both say
CONVERGED.
