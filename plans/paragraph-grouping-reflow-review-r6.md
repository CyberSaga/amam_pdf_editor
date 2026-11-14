# Review round 6 (narrow) of `paragraph-grouping-reflow.md` revision 6 (2026-11-14): NOT CONVERGED

Record for writing revision 7 without the transcripts. R = deep-reasoner (Opus): 5 majors (M1-M5), minors.
X = Codex `gpt-6.1-sol`: 3 majors, all inside R's M1-M3. No blocker. Nothing is implemented. Both: revision 6
broke nothing previously RESOLVED; the donor transaction is untouched; F4, F5, F6, F8, the X minor and the
"no silent font change" rule on the model side are RESOLVED.

## Open findings (all in the layout arithmetic of C.3 / C.6 (f)(g), plus one classification)

- **M1 (R; X 1) one fit definition.** `natural width`, hanging whitespace and the first atom's lead-in are
  used differently by the breaker, (g) 5 and (g) 6. A correct ragged Latin line `the quick ` over `brown`
  fails (g) 5 if the hanging space is counted, or (g) 6 rejects a correct break if it is not; an atom-less
  `join_sep` behaves the same (pulling U up would materialize a space (g) 6 does not count); the first
  atom's own lead-in gives a negative share. Also no check requires a soft break to be LEGAL (at a B.1
  opportunity, kinsoku respected), and B.1 does not list the `join_sep` pair across a former line end as an
  opportunity. Change, stated once in C.3 and used by the breaker, (g) 5 and (g) 6: natural width =
  advances from the first atom to the last non-whitespace atom + lead-ins of every atom except the first;
  fits = natural width + L's trailing whitespace (or the space C.1 would materialize) + U's C.1 lead-in +
  U's width <= available width, with (f)'s tolerance; (g) 6 adds "every soft break is at an opportunity
  and respects kinsoku"; B.1 makes the `join_sep` pair an opportunity. S5: a Latin soft break at a space.
- **M2 (R; X 2) alignment.** For centred or right-aligned text the anchor is the centre or right edge, but
  (g) 5/6 use it as the line start; a zero-opportunity line divides by zero; B.1 classifies non-last
  right-aligned lines as justified. Change (smallest, owner guidance): v1 admission refuses centred and
  right alignment (`tier2r:alignment`), the chain continues to Tier 0/1; a line with no opportunity has
  share 0 without division.
- **M3 (R; X 3) which new line is justified.** Nothing decides it; (f) trusts the plan, a negative share
  (compression) passes, an eligible line left ragged passes. Change, one rule for C.3, (f), (g) 5: a new
  line is justified iff the paragraph has a B.1-justified source line, the line ends at a soft break, it
  has at least one opportunity, and 0 <= (available width - natural width) / opportunities <= 0.5 em;
  then share = exactly that value; otherwise share = 0 (0.01 pt).
- **M4 (R) admission vs plan failure.** `clip_too_tight` "fails the plan" (terminal under C.0 (1)) while B.1
  says every `tier2r:` failure continues; `glyph_unavailable` is raised during planning, so typing a
  character no font holds would be a dead end. Change: every `tier2r:<reason>` (the B.1 rules,
  `restyle_requested`, `hard_break_edit`, `no_insert_owner`, `glyph_unavailable`, `clip_too_tight`,
  `alignment`) continues the chain; terminal are only `REFLOW_DOES_NOT_FIT`, `PREVIEW_STALE` and any
  failure once a patch set exists.
- **M5 (R, rare) verbatim threshold.** A run copied verbatim with |d| up to 0.005 keeps the source share
  while the next run's `Tm` uses `share_new`; three opportunities at d = 0.004 give 0.012 > 0.01 and (g) 5
  fails. Change: copy verbatim only when d = 0 (1e-6).

## Minors

- S0 probe 2 should assert (g) 5 and raster for the re-justified line ((a) now holds by construction).
- "A one-line Tier 0 session that overflows" cannot happen with Tier 2R first: reword (C.7, S7).
- C.7 bookkeeping citation: `edit_commands.py:859-861, 932-937` (the cited range includes the storage
  restore the text says is skipped).
- View: the rebuild offer (`view/text_edit_reasons.py:149-158, 190-192`) appears for any new code; a user
  who consents after `REFLOW_DOES_NOT_FIT` gets nothing. Add the terminal codes to `_NOT_REBUILDABLE` + S7
  test. Unverified: whether the consent text (`controller/pdf_controller.py:4206-4207`) names the font
  change.
- C.3 baselines and (g) 3/4 ignore the C.8 vertical move.
- A typo fix re-flows to the segment end when the producer's breaks are not greedy under C.3 (unverified
  on the reference file): add a breaker test that the unchanged paragraph comes back with its own lines
  (S0 probe).

## Handoff

Revision 7: M1-M5 and the minors above; nothing else. The pattern of rounds 5 and 6 is that C.6 (g) restates
the breaker in other words and the two drift. Revision 7 should DEFINE fit, natural width, justification
and legality once (C.3) and have (g) call that definition on replayed geometry. Then a narrow round 7.
S0 only when both say CONVERGED.
