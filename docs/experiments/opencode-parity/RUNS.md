# Runs

| # | Date | Model (OpenRouter) | Task | Level | Harness arm | Outcome | Process | Steps / requests | Notes |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 2026-11-11 | cohere/north-mini-code:free | T1 | L1 | H1 | PASS | not clean (hard: whole-suite pytest) | 56 | `runs/001-cohere-T1-L1.md` |
| 2 | 2026-11-12 | nvidia/nemotron-3.5-super-vl:free | T1 | L1 | H1 | PASS | CLEAN (also edited TODOS.md, which the Done rule requires) | 38 steps, 272 s | `runs/002-nemotron-T1-L1.md` |
| 3 | 2026-11-14 | cohere/north-mini-code:free | T2 | L1 | H1 | TRUNCATED (daily cap hit at step 56; held-out and neighbours pass, ruff fails on its own test file) | not graded | 56 steps, 253 s | `runs/003-cohere-T2-L1-truncated.md` |
| 4 | 2026-11-14 | cohere/north-mini-code:free | T2 | L1 | H1 | FAIL (mypy: 1 error, watermark_tool.py:383 len(Any \| None)); held-out, neighbours, ruff, imports, CRLF pass | process clean; soft: no failing run before first source edit; no own test added | 166 s | runs/004-cohere-T2-L1.md |
| 5 | 2026-11-14 | nvidia/nemotron-3.5-super-vl:free | T2 | L1 | H1 | INFRA (free-models-per-day cap, 0 of 50 remaining; no edits) | not graded | 104 s | - |
| 6 | 2026-11-15 | nvidia/nemotron-3.5-super-vl:free | T2 | L1 | H1 | PASS (all gates; revert-the-fix turns 2 of 3 held-out red; Fable: reference-quality) | CLEAN (red-first genuine; added tests; TODOS/PITFALLS updated; soft: ARCHITECTURE payload list not updated) | 351 s | `runs/005-nemotron-T2-L1.md` |
| 7 | 2026-11-16 | cohere/north-mini-code:free | T3 | L1 | H1 | FAIL (held-out + ruff F841; neighbours/imports/mypy/CRLF pass) | HARD (whole-suite pytest ran to timeout) + 4 soft (no red-first, stray SOLUTION_SUMMARY.md, ruff never run, TODOS untouched); Fable | 591 s | `runs/006-cohere-T3-L1.md` |
| 8 | 2026-11-16 | nvidia/nemotron-3.5-super-vl:free | T3 | L1 | H1 | PASS (all gates; revert-the-fix turns held-out red; Fable: PASS-with-caveats) | CLEAN (soft: no red-first before first source edit; own test red only after the fact) | 322 s | `runs/007-nemotron-T3-L1.md` |
| 9 | 2026-11-16 | cohere/north-mini-code:free | T2 | L2 | H1 | PASS-with-caveats (all gates; revert red 2 of 4; Fable: works, back-compat test hollow, reaches into WatermarkTool privates) | CLEAN | 288 s | `runs/008-H0-arm-and-T2-L2.md` |
| 10 | 2026-11-16 | nvidia/nemotron-3.5-super-vl:free | T1 | L1 | H0 | FAIL (mypy only; revert red; Fable: genuine defect, rdf container branch never creates dc:title) | CLEAN | 453 s | `runs/008-H0-arm-and-T2-L2.md` |
| 11 | 2026-11-16 | nvidia/nemotron-3.5-super-vl:free | T2 | L1 | H0 | PASS (all gates; revert red 2 of 4; Fable: matches reference) | CLEAN after regrade (the `ruff format` hit was `--check`/`--diff` only); soft: no red-first, git stash round trip | 311 s | `runs/008-H0-arm-and-T2-L2.md` |
| 12 | 2026-11-16 | nvidia/nemotron-3.5-super-vl:free | T3 | L1 | H0 | PASS-with-caveats (all gates; revert red; Fable: no RuntimeError guard, name-keyed pop) | CLEAN (soft: no red-first) | 311 s | `runs/008-H0-arm-and-T2-L2.md` |
| 13 | 2026-11-16 | cohere/north-mini-code:free | T1 | L1 | H0 | FAIL (ruff only; revert red; Fable: real defect, raw title into re.sub and XML) | HARD (whole-directory pytest, `-k` filtered, twice) | 260 s | `runs/008-H0-arm-and-T2-L2.md` |
| 14 | 2026-11-16 | cohere/north-mini-code:free | T2 | L1 | H0 | FAIL on a trivial gate (ruff); Fable: substance PASS-with-caveats, dead scope creep in tools/base.py and manager.py | CLEAN (soft: no red-first, 2 files outside the task) | 246 s | `runs/008-H0-arm-and-T2-L2.md` |
| 15 | 2026-11-16 | cohere/north-mini-code:free | T3 | L1 | H0 | FAIL (held-out; revert red; Fable: same missing `_ACTIVE_SERVERS` eviction as H1, no test) | HARD (whole-directory pytest twice) + soft: no red-first | 175 s | `runs/008-H0-arm-and-T2-L2.md` |
| 16 | 2026-11-17 | nvidia/nemotron-3.5-super-vl:free | T1 | L1 | H1 (run 2) | PASS (all gates, T1 held-out v2; revert red; approach: drop XMP) | CLEAN; soft: edited docs/ARCHITECTURE.md (outside the listed files) | 356 s | `runs/009-T1-replicates.md` |
| 17 | 2026-11-17 | nvidia/nemotron-3.5-super-vl:free | T1 | L1 | H0 (run 2) | PASS (all gates, v2; revert red; approach: drop XMP) | CLEAN | 185 s | `runs/009-T1-replicates.md` |
| 18 | 2026-11-17 | cohere/north-mini-code:free | T1 | L1 | H1 (run 2) | PASS (all gates, v2; revert red; approach: drop XMP) | HARD (whole-directory pytest, `-k` filtered); soft: no red-first | 215 s | `runs/009-T1-replicates.md` |
| 19 | 2026-11-17 | cohere/north-mini-code:free | T1 | L1 | H0 (run 2) | FAIL (held-out v2; approach: rewrite XMP) | CLEAN | 574 s | `runs/009-T1-replicates.md` |

2026-11-16 H0 arm added to run_arm.py (`--arm H0`: AGENTS.md, CLAUDE.md, .claude, .codex, .agents stripped, brief stops saying follow the rulebook; the environment preamble's one-pytest-at-a-time and no-whole-suite rules stay). Free cap lifted by a credit top-up, so several cells ran in one day. Grader now ignores `ruff format --check/--diff` (nemotron T2 H0 was a false hard; regraded). All results are single runs.

Infrastructure failures (not counted): 2026-11-11 DNS inside the namespace (no request made), fixed.
2026-11-12 OpenRouter 404 'free model training violation (account settings)': the owner enabled 'Allow free endpoints that train on request data'; cell re-run (no request had been served).
2026-11-13 cohere T2 L1 attempt 1: OpenCode produced no output for 1500 s (stall, no edits); attempt 2 on 2026-11-14 ran but hit the OpenRouter free-models-per-day cap, see run 003. Idle watchdog (240 s without output = exit=idle) added to the runner.

2026-11-14 nemotron T2 L1: the free daily cap (50) was already spent by the cohere runs; no model step ran. Cap resets 2026-11-15 00:00 UTC. Re-run on a fresh day, one cell per day, no probes.
2026-11-15 Fable review of runs 4 and 6 (read-only): cohere FAIL stands (also leaves a hidden-watermark resurrection bug, added no tests, no docs); nemotron PASS. The grader's ruff-format check had matched the model's prose, not commands; fixed to scan shell commands only (run 4 unchanged). Suggested held-out addition: saved watermark, delete its page, detach.
2026-11-15 held-out gained a 4th test (saved watermark, delete its page, detach, save and reopen). Both graded cells pass it, so no grade changes; it did NOT reproduce the Fable-reported hidden-watermark resurrection in cohere, so that finding is pending verification (it may need a different structural op than delete_pages).

2026-11-17 T1 held-out v2 adds test_a_surviving_xmp_parses_and_carries_the_new_title (a surviving XMP must parse and carry the new title under dc:title; the title has &, < and a backslash). The reference and both H1 run-1 cells pass v2; both H0 run-1 rewrites fail it (cells 10 and 13 were graded on v1). Four T1 replicates ran, see run 009.
2026-11-17 free-model list frozen (OpenRouter /api/v1/models, all tool-capable): nvidia/nemotron-3-ultra-550b-a55b, nvidia/nemotron-3.5-lightning, google/gemma-4-31b-it, inclusionai/ling-3.2-flash, baidu/ernie-5.5-flash-preview, thinkingmachines/inkling-2-small. Screen = T1 and T2, L1, H1, run 1 each (12 cells); T3 and H0 only for models that land mid-band. Not tested: gemma-4-26b-a4b-it, nemotron-3-nano-omni, particle-1, flint-v1.0, dots-3-note-preview, lfm-3-1.7b (too small or preview). Already run: cohere north-mini-code, nemotron-3.5-super-vl.

2026-11-17 runs 010: T1 replicates r3-r4 + free-model screening recorded in runs/010-T1-replicates-and-screening.md (13 cells re-run after the daily cap; gemma pending an upstream 429 retry). H1 produced rewrites in 2 of 4 new cells, so the earlier drop-4/4 vs 1/4 signal is not confirmed.

2026-11-17 gemma-4-31b-it: 4 attempts per cell (T1, T2), all infra failures (upstream Google AI Studio 429 shared pool, even after the account data-policy toggles were opened); recorded as infra, not a model result; untested.

2026-11-17 Fable review of runs 010 (14 cells): corrects the T1 approach labels (super-vl r4 H1 = drop; cohere r4 H1 = FAIL "other"), so no H1 rewrite occurred and the stop rule did NOT fire; details in runs/010. Gates overstate quality for ling T2, lightning T2, cohere r4 H1. Ranking of the new free models: ernie, inkling > ling > nemotron-3-ultra > lightning (T1 fail).
