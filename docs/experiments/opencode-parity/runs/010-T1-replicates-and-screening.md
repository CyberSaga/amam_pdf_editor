# 010 T1 replicates (runs 3-4) and free-model screening (L1, H1, run 1)

Date 2026-11-17. First attempt hit the OpenRouter free daily cap (1000/day) mid-chain; 13 cells were infra failures (moved to the harness `runs/_infra/`, not counted) and re-run after the 00:00 UTC reset. gemma-4-31b-it was also blocked by an upstream Google AI Studio 429 (shared pool); retried afterwards.

## T1 replicates (held-out v2; gates + revert-the-fix; approach read from the diff)
| cell | arm | gates | approach |
|---|---|---|---|
| nemotron-3.5-super-vl r3 | H1 | PASS | drop XMP |
| nemotron-3.5-super-vl r3 | H0 | no result.json (never finished; not counted) | - |
| nemotron-3.5-super-vl r4 | H1 | PASS | REWRITE (parse XMP, replace dc:title/creator) |
| nemotron-3.5-super-vl r4 | H0 | PASS | drop XMP |
| cohere r3 | H1 | FAIL | - |
| cohere r3 | H0 | FAIL | - |
| cohere r4 | H1 | PASS | REWRITE (string-level XMP update) |
| cohere r4 | H0 | PASS | drop XMP |

Stop rule fired: H1 produced rewrites (nemotron r4, cohere r4). The earlier "H1 drops 4/4 vs H0 1/4" (Fisher p~0.07) does not hold; H1 now has rewrites in 2 of the 4 new H1 cells with a result. Verdict: no demonstrated H1-vs-H0 effect on approach choice; the earlier gap looks like run-to-run variance. The remaining 2 planned replicates were not run (stop rule). Diff-only classification, not yet Opus-reviewed.

## Screening (L1, H1, run 1)
| model | T1 | T2 |
|---|---|---|
| nemotron-3-ultra-550b | PASS | PASS |
| nemotron-3.5-lightning | FAIL (heldout/neighbours/ruff/mypy red; fails the new XMP-parses test) | PASS |
| ling-3.2-flash | PASS (26 min) | PASS (25 min) |
| ernie-5.5-flash-preview | PASS | PASS (21 min) |
| inkling-2-small | PASS | PASS |
| gemma-4-31b-it | pending retry (upstream 429) | pending retry |

All PASS cells: revert-the-fix turns the held-out red (T1: 2 failed/1 passed; T2: 2 failed/2 passed). Process reports and Opus/Fable review of the diffs are still owed; the PASS verdicts above are gate-only.
Takeaway: only lightning fails; the other four are at or near the ceiling on T1/T2 so they do not discriminate H0/H1 either. T3 and H0 only make sense for lightning and any mid-band model.

## Fable diff review (2026-11-17) — CORRECTS the approach column above
My first approach labels came from the top of each diff and were wrong for two cells: nemotron-3.5-super-vl r4 H1 is a DROP (the XMP helper I saw was not the fix path), and cohere r4 H1 is neither drop nor rewrite (`set_xml_metadata("")` leaves a referenced empty /Metadata stream) and Fable grades it FAIL although the gates passed. So the "stop rule fired" statement above is withdrawn: no new H1 cell produced a true rewrite. Updated tally of new T1 replicates: H1 = drop, drop, other(FAIL); H0 = drop, drop (+ cohere r3 both arms failed gates). Combined with earlier cells H1 now leans drop (about 6 of 7 usable) and H0 about 3 of 6, which is weaker than 4/4 vs 1/4 and well short of significance. Primary endpoint stays inconclusive; the planned remaining replicates (8 per arm) are NOT cancelled by the stop rule after all.
Capture gap: `.full.diff` has tracked-file changes only, so files a model created (inkling T1 core module, nemotron-ultra T2 test file) are missing from the review; capture untracked files too (`git add -N` before diff) for later cells.

| cell | Fable verdict | main concern |
|---|---|---|
| ernie T1 | PASS | none material; real save/reopen test |
| ernie T2 | PASS-WITH-CONCERNS | PITFALLS claims a UI measurement nothing backs; code/tests best of set |
| ling T1 | PASS | unverifiable run counts in TODO |
| ling T2 | PASS-WITH-CONCERNS | unsaved page change on a saved watermark reverts at next structural op, untested |
| nemotron-3-ultra T1 | PASS-WITH-CONCERNS | silent `except: pass` around the delete |
| nemotron-3-ultra T2 | PASS-WITH-CONCERNS | TODO ticked inaccurately, no ARCHITECTURE/PITFALLS |
| lightning T2 | PASS-WITH-CONCERNS (weakest) | writes tool private dicts from controller; unsaved page change reverts; no tests/docs |
| lightning T1 | FAIL | deleted four unrelated PDFModel methods; regex only matches plain dc:title |
| super-vl T1 r3 | PASS-WITH-CONCERNS | TODO ticked with stale text, no ARCHITECTURE |
| super-vl T1 r4 | PASS-WITH-CONCERNS | false "never leaks at any level" comment, silent except, no docs |
| cohere T1 r4 H1 | FAIL | empty referenced /Metadata, dead regex helpers, vacuous fixture |
| cohere T1 r4 H0 | PASS-WITH-CONCERNS | minimal 2-line fix, no assertion/docs |
| inkling T1 | PASS-WITH-CONCERNS | core module not in captured diff (unreviewable) |
| inkling T2 | PASS | minor broad except |

Observations: docs+tests are complete for ernie, ling, inkling; absent for cohere, lightning, super-vl r4. On T2 the discriminator the gates miss is page identity: ernie, inkling, nemotron-ultra re-seed it (like the current tree); ling and lightning can revert an unsaved page change. Gates alone overstate quality for ling T2, lightning T2, cohere r4 H1.
