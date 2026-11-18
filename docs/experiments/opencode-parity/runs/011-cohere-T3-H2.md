# Run 011: cohere T3 L1, arm H2 (runner-enforced denials), runs 1 and 2

2026-11-18. Model openrouter/cohere/north-mini-code:free, task T3 shutdown hand-off, brief L1, `--arm H2` (opencode.json denies `pytest*`, whole-suite run_suite, `ruff format`, `git push`, `git commit`). Graded by gates only. NO review (owner: record only; Fable unavailable). Revert-the-fix not run: held-out already fails in both.

| Cell | Seconds | Gates | Process |
|---|---|---|---|
| r1 | 315 | FAIL: held-out; neighbours, ruff, imports, mypy, crlf pass | HARD: attempted whole-suite `pytest test_scripts/ -k "shutdown"` (the H2 denial blocks it, so recorded as an attempt); soft: no red-first, wrote CURRENT_STATE.md and FIX_SUMMARY.md |
| r2 | 175 | FAIL: held-out and ruff (4 errors, all in its own scratch tests: E402, 3x F401); neighbours, imports, mypy, crlf pass | no hard; soft: no red-first, wrote test_server_shutdown.py and test_server_shutdown_fix.py |

Shared held-out failure: both runs wrote `service._process is None` in `finish_owned_shutdown` (main.py ~479), but `QLocalServer` has no `_process`, so `qapp._pdf_owned_shutdown()` raises AttributeError and the shutdown never completes.

Comparison, cohere T3 L1: H1 FAIL (run 006), H0 FAIL (cell 15), H2 FAIL x2. H2 did not change the outcome; the denial removed the whole-suite run but not the missing red-first or the untested attribute assumption. n=2, no review.

Infra (not counted): the first attempts of both cells were an idle-watchdog stall (r1) and a daily-cap hit (r2); moved to `runs/_infra/` and re-run.
