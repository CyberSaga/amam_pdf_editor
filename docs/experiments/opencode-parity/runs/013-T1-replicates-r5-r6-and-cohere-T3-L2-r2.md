# Run 013: T1 replicates r5-r6 (H1 and H0, nemotron super-vl and cohere) and cohere T3 L2 r2

2026-11-18. Held-out v2. Gates plus revert-the-fix for every gate-pass (held-out red after reverting the model's source edits). Approach labels read from the diff only; NO Fable/Opus review (Fable unavailable, owner: no substitute). Earlier diff-only labels flipped on review (run 010), so treat these as provisional.

| Cell | Result | Approach | Notes |
|---|---|---|---|
| nemotron r5 H1 | FAIL held-out v2 | rewrite (`_sync_xmp_metadata`) | edited docs/PITFALLS/TODOS too |
| nemotron r5 H0 | FAIL mypy (2 union-attr errors, pdf_model.py:4651-4652); held-out passes | drop (sets /Metadata key to null, relies on GC) | the only gate failure |
| nemotron r6 H1 | PASS, revert red | drop (`del_xml_metadata` in try/except) | |
| nemotron r6 H0 | FAIL held-out; no files changed | none | the model made no edit |
| cohere r5 H1 | FAIL ruff (F401 unused `tempfile` in its own new test); held-out passes | drop | extra XMP_FIX_SUMMARY.md |
| cohere r5 H0 | PASS, revert red | drop (try/except) | |
| cohere r6 H1 | PASS, revert red | drop | |
| cohere r6 H0 | PASS, revert red | drop (try/except) | its first attempt was killed by the host's memory-pressure reaper; moved to `_infra/cohere_T1_r6_H0_killed` and re-run |
| cohere T3 L2 r2 | PASS, revert red | | no hard process violation, soft: no red-first |

No hard process violations in any T1 cell here (grader reports none for the cells I inspected: both nemotron r5, cohere r5 H1, r6 H0 nemotron).

Grader artifact: cohere T3 L2 r2 lists 392 changed files because of LF/CRLF noise in the sandbox; the real diff (`--ignore-space-at-eol`) is main.py plus the held-out test, so it is a one-file source change.

## Approach tally (diff-only labels, all T1 runs 1-6 except unreviewed disagreements)
Runs 5-6 only: H1 drop 3 of 4 (nemotron r6, cohere r5, cohere r6; nemotron r5 rewrote); H0 drop 3 of 3 with an edit (nemotron r5, cohere r5, cohere r6; nemotron r6 made no edit). So runs 5-6 do not reproduce the H0-rewrites tendency: the H1 vs H0 approach gap shrinks further. Combined with the earlier tally (H1 about 6/7 drop vs H0 about 3/6) the H1-vs-H0 effect on approach is not supported; the extra experiment arm (files vs "follow the rulebook" sentence) has no effect to explain yet.

## gemma-4-31b-it:free
Re-attempt 2026-11-18: 2 tries per task (T1, T2), all upstream 429 infra failures (93-99 s each). Skipped per the owner's rule; untested.
