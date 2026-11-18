# Run 012: records that were pending (H2 probe, cohere T3 L2 H1, cohere T1 H2, GLM-5.3 x6, gemma infra)

Recorded 2026-11-18. Gates plus revert-the-fix (held-out turns red when the model's source edits are reverted, tests kept) were run for every PASS below. NO review of any cell (Fable unavailable; owner: no substitute model).

## H2 probe (2026-11-17)
`opencode.json` in the sandbox with `permission.bash` `"*": allow`, `pytest*` and `python -m pytest*` denied, run under `--auto`: the model was asked to run `echo`, `pytest --version`, `python -m pytest --version`. The echo ran; both pytest commands were denied. So H2 is feasible by permission rules alone, no PATH shim. Limit seen in cell 23 below: a denial is a prefix glob, so `cd X && python3 -m pytest ...` or `python3 -m pytest` is not matched and still ran.

## cohere/north-mini-code:free
| Cell | Arm | Gates / revert | Hard process | Soft | s |
|---|---|---|---|---|---|
| T3 L2 r1 | H1 | PASS all, revert red | whole-suite pytest (`-k "single_instance" --collect-only`) | no red-first | 278 |
| T1 L1 r1 | H2 | PASS all, revert red | `cd ... && python3 -m pytest test_scripts/ -k metadata -v` (slipped the `pytest*` deny, a prefix glob) | none | 103 |
| T1 L1 r2 | H2 | PASS all, revert red | none | none | 201 |

T3 L2 H1 is the only cohere T3 pass so far (L1 fails under H1, H0 and H2); it is one run, a replicate (r2) is queued.

## z-ai/glm-5.3 (paid; owner allowed it for this run; L1 and L2 H1, run 1)
All six PASS every gate and revert-the-fix; no hard process violations.

| Task | Brief | s | Notes (from the changed-file list, not reviewed) |
|---|---|---|---|
| T1 | L1 | 725 | also model/pdf_xmp.py (new), docs/ARCHITECTURE, PITFALLS, TODOS |
| T1 | L2 | 476 | docs/ARCHITECTURE, PITFALLS, TODOS |
| T2 | L1 | 725 | also model/tools/manager.py, docs |
| T2 | L2 | 410 | grader soft flag: no source edit seen in the transcript (edits are in the diff) |
| T3 | L1 | 549 | also plans/app-performance-v2.md, docs; same soft flag |
| T3 | L2 | 930 | docs; same soft flag |

GLM updated ARCHITECTURE/PITFALLS/TODOS in every cell (the rulebook's done-means list); the grader counts only ARCHITECTURE as outside-the-task. Fable review of the six diffs is pending (wait for Fable; no substitute).

## gemma-4-31b-it:free
T1 and T2, 4 attempts each on 2026-11-17: all upstream Google AI Studio 429 (shared pool, even with the data-policy toggles on). Infra, no model result. Re-attempt 2026-11-18: 2 tries per task, then skip (outcome in RUNS.md).
