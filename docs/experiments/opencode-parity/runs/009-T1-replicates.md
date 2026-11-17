# Run 009: T1 replicates (run 2, both arms, both models)

Held-out v2 (see RUNS.md note). Revert-the-fix turns the held-out red in all four. No Fable review of these four (Fable was used for run 008); approach read from the diffs.

| Cell | Approach | Result |
|---|---|---|
| nemotron T1 H1 r2 | del_xml_metadata, guarded by xref_xml_metadata | PASS; also edited docs/ARCHITECTURE.md and PITFALLS |
| nemotron T1 H0 r2 | del_xml_metadata | PASS |
| cohere T1 H1 r2 | del_xml_metadata in try/except | PASS; whole-directory pytest (-k metadata) is a hard process violation |
| cohere T1 H0 r2 | hand-built XMP string (`<x:dc:title>` tags, values unescaped) | FAIL v2 held-out |

T1 approach across the two runs per cell: H1 chose drop 4 of 4 (nemotron r1, r2; cohere r1, r2). H0 chose rewrite 3 of 4 (nemotron r1, cohere r1, cohere r2) and drop once (nemotron r2). Both rewrites that were reviewed shipped a real defect. Still small n and the TODO offers rewrite-or-drop, so read it as a consistent tendency, not proof; the rulebook mentions nothing about XMP, so the mechanism is unexplained (pending verification).

## Transcript inspection (Opus, 2026-11-17): why H1 drops and H0 often rewrites

Eight T1 transcripts (r1, r2 x both arms x both models). Precedent = the model saw `pdf_optimizer.py:590 working_doc.del_xml_metadata()` before its first source edit.
- Choice: H1 drop 4/4; H0 rewrite 3/4. Precedent seen: H1 2/4, H0 3/4, so exploration depth does not separate the arms. Nemotron dropped whenever it saw :590; cohere tracks the arm (H0 saw :590 twice and still rewrote).
- Process endpoints (H1 / H0): test or fixture added 4/4 and 4/4; TODOS updated 3/4 and 2/4; PITFALLS 1/4 and 0/4; red-first 1/4 and 1/4; no model opened a rulebook file with a tool (0/8).
- Rulebook injection evidence: nemotron H1 r1 reproduced the AGENTS.md report fields and said "Per the rulebook"; r2 loaded the scope-fence skill. Cohere H1 transcripts show no rulebook trace.
- No rulebook rule mentions XMP; no transcript cites rulebook text as the reason to drop. Best-supported reading: weak tendency (possibly a generic minimal-change prior from the injected rulebook, unverified) plus chance. One-sided Fisher p about 0.07 on 4/4 vs 1/4. Rulebook files vs the removed "follow the rulebook" sentence cannot be separated, since H0 removes both.
- To separate: two extra arms (files without the sentence; sentence without the files), record precedent exposure per cell, at least 3 more replicates per cell. Eight replicates (run 3 and 4) were launched 2026-11-17.
