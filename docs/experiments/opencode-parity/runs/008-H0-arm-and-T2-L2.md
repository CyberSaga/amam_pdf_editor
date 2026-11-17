# Run 008: H0 arm (six cells) and cohere T2 L2

All single runs, Fable-reviewed 2026-11-17 (read-only). H0 = no rulebook; the preamble still says one pytest at a time and never the whole suite. Revert-the-fix turned the held-out red in every cell.

| Cell | Verdict | Reason |
|---|---|---|
| cohere T1 H0 | FAIL | title put raw into re.sub replacement and XML (a backslash raises re.error after /Info changed; & and < corrupt the packet); ruff errors trivial; no TODOS |
| cohere T2 H0 | FAIL on ruff, substance PASS-with-caveats | import calls tools.watermark.on_session_open directly, so the base.py/manager.py edits are dead scope creep; receiver watermark-modified flag never set; one of three own tests discriminates (pending verification) |
| cohere T2 L2 (H1) | PASS-with-caveats | PDFModel reaches into WatermarkTool privates; back-compat test hollow; two near-duplicate test files |
| cohere T3 H0 | FAIL | same missing _ACTIVE_SERVERS eviction as H1; main.py only, no test |
| nemotron T1 H0 | FAIL | rdf container branch hangs Alt/Seq/Bag on rdf:Description, never creates dc:title; mypy errors trivial |
| nemotron T2 H0 | PASS | matches the reference; ruff format only with --check/--diff (grader false positive, fixed); git stash round trip |
| nemotron T3 H0 | PASS-with-caveats | equivalent to release_server on the tested path; no RuntimeError guard; name-keyed pop |

H0 vs H1 (Fable): rulebook injection in H1 is verified, so the arms differ. cohere T3 fails identically in both arms (model limit). nemotron T2/T3 same quality in both. cohere T2 fails a different trivial gate each time (noise). T1: both models chose the reference drop in H1 and passed, both chose a rewrite in H0 and shipped a real defect; two of two is an observation, not an effect. Whole-directory pytest by cohere appears in both arms and the rule is in the preamble of both, so that is the model. Rulebook-shaped differences (nemotron H1 had real red-first, TODOS and PITFALLS on T2; H0 had none of them on T2/T3) are still n=1.
Next: replicate T1 in both arms; extend T1 held-out (surviving XMP must parse and carry the new title under dc:title). nemotron T2 and T3 H0 both report 311.3 s: distinct transcripts, so a coincidence.
