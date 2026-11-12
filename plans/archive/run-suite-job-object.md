# run_suite.py: Windows Job Object kill path (orphan classes 1 and 3, the spawn race)

## Current state and next step
- 2026-11-03. Owner ruling: "Job Object design (full)", three-step verification (TODOS line 17).
- Steps (1) and (2) DONE and merged (commit 28b27d1 on feat/true-text-edge-cases): `test_run_suite.py` 198 passed
  (185 + 13 new), ruff clean; red light 16 failed / 182 passed before the code.
- Step (3), local half DONE 2026-11-03: full `scripts/run_suite.py` on 28b27d1 = 9640 passed / 0 failed / 17 skipped /
  0 hung / 0 crashed (2230 s, `--parallel-lanes` default); no "could not put pid" warning and no "exited and left"
  line in the run log. CI half OPEN: needs an owner push; windows-latest answers the CI-only questions below;
  read the advisory ubuntu cell by hand (the 11 job tests skip there, the POSIX kill tests must stay green).
- Docs landed with 28b27d1: TODOS line 17, PITFALLS Residual update + new entry + index, ARCHITECTURE 7.4.
- Owner calls left open by the review (one-line changes each, any of them re-enters the three-step rule):
  the spawn-race test stretches every walk 20 ms through the `_win_descendants` seam (a load model; idle-speed
  shapes passed before the fix); a failed thread resume in `attach` raises (run aborts) while a failed job
  create/assign only warns and falls back to the walk; `_job_drained` treats a job it cannot query as drained;
  `_verify` polls the job once after the member waits used the deadline (a still-draining job can log `-pid`).
- Next: after CI is green, `git mv` this plan to `plans/archive/`; POSIX E5 and the exited-root group stay in TODOS.

## Goal
One mechanism that ends orphan class 1 (the root exited, a descendant survives and holds the log), class 3
(a descendant behind a dead intermediate parent) and the spawn race (a process spawned between the late
enumeration and its parent's TerminateProcess) on Windows, plus a backstop when `run_suite.py` itself dies:
one Job Object per supervised child with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`. Measurements and the design
come from the session report `m1/orphan/orphan_m.md` ("Landing design", items 1-5 and 7; item 6, the
pinned-union fallback, was rejected by the owner).

## Modules
- `scripts/run_suite.py`: `_WindowsTree.popen_kwargs` (CREATE_SUSPENDED), new seams `_ProcessTree.attach` /
  `reap` / `release`, the job in `_WindowsTree._signal` / `_verify`, `kill` releases the job last, `supervise`
  attaches first, reaps at the three exited-root sites and releases in a `finally`; module seam `_reap_tree`.
- `test_scripts/test_run_suite.py`: new FAKE_CHILD modes (bounded sleeper, root that exits leaving a
  grandchild, intermediate that dies, spawn loop), real-process job tests, two re-pins.

## Steps
0. This plan.
1. Baseline (untouched worktree), then the red-light tests (design item 5) and their red run.
2. Design items 1+2 (see Decisions D1), rerun; item 3, rerun; item 4, rerun; item 5 (docstrings), final rerun.
3. Not here: full `scripts/run_suite.py` + CI in the main checkout after merge-back.

## Decisions
- D1. Items 1 and 2 land as one step. `CREATE_SUSPENDED` alone leaves every supervised child suspended until
  something resumes it: every real-process `supervise` test would sit at its stall/ceiling (60-120 s) and
  prove nothing. Item 1 is applied first in the same edit; the rerun follows item 2's resume.
- D2. The job handle is closed by a new `release(proc)` seam, not by `close(members)`: `close` has no proc and
  `_close_members` / the tests call it with members only. `kill` calls `release(proc)` in its `finally`
  after `close(targets)` (the design's "close() closes the job handle last"); `reap` and `supervise`'s
  `finally` call it too; it is idempotent (pop with a default).
- D3. Survivor marker for a job that still has active processes: `-proc.pid`, the marker `_PosixTree._verify`
  already returns for "the process group still has members".
- D4. A resume failure (no thread of the pid found, `OpenThread` or `ResumeThread` failed) raises `OSError`
  from `attach`: a child that never runs would only be ended by the stall kill much later; `supervise`'s
  except handler kills the suspended tree and re-raises. Job creation / assignment failures only warn and fall
  back to the walk-based kill (design item 2).
- D5. `reap` terminates the job unconditionally (a no-op on an empty job) and logs a warning only when the job
  still had active processes; `supervise` logs `reap`'s survivors through the `_reap_tree` seam with the same
  "not gone after the kill" text as the two kill sites.
- D6. POSIX: `attach` / `reap` / `release` are no-ops. E5 (a descendant that leaves the process group) stays a
  TODO; so does the POSIX shape of class 1 (an exited root's group left behind; `killpg` after the exit would
  reach it, unmeasured here).
- D7. `supervise` reaches `reap` through a module seam `_reap_tree(proc)` (like `_kill_tree` / `_descendants`),
  which logs reap's survivors with the kill sites' text; S1 became `try/except TimeoutExpired/else`.
- D8. `_verify` / `reap` wait with `_job_drained`: poll `ActiveProcesses` every 10 ms up to the bound and
  re-issue `TerminateJobObject` on every poll (a process that joined while the previous terminate ran); an
  unqueryable job warns and ends the wait (it is not reported as a survivor).
- D9. Test-only: the spawn-race test stretches every walk by 20 ms through the `_win_descendants` seam (see
  Dead ends) and its sleepers end by themselves after 5 s; all other new grandchildren after 40 s.

## Questions only CI can answer (from the report, not answered locally)
1. Is the windows-latest step process already in a job, and does `AssignProcessToJobObject` succeed nested
   under it (ACCESS_DENIED would force the fallback path)? Does the runner job set
   `JOB_OBJECT_LIMIT_BREAKAWAY_OK` / `SILENT_BREAKAWAY_OK` (decides whether the supervised child nests under the
   runner job or starts fresh under the supervisor's own job; here SILENT_BREAKAWAY_OK is set), and does a job
   close on the runner kill anything the runner still needs?
2. Does the CI interpreter (setup-python) have a venv redirector? Decides whether a post-exit walk alone would
   have worked there; locally it does not.
3. `py-spy dump --native --pid` against a job member (not installed here), and against the
   suspended-then-resumed root.
4. ubuntu/macos: does any test or lib in the suite start a new session (E5), is pidfd available in the sandbox?
5. Timing: does `CREATE_SUSPENDED` + thread resume change anything for coverage or the `--cov` subprocess hooks
   (not exercised here).
6. (added by the lane) Does a supervised child get a `conhost.exe` of its own on windows-latest (a runner process
   without a console)? A conhost in the child's job would make every normal exit log "exited and left 1
   process(es)" and fail `test_job_supervise_clean_exit_closes_the_job_and_reports_no_orphan`; locally no such
   process appeared (every run here, the nested probe included).

## Dead ends
- Spawn-race test at idle-machine speed (venv sleepers, then E3's base-interpreter spawner every ~1 ms, kill
  once 8 were launched): 0 of 10 trials left a survivor before the job existed, so the test passed before the
  implementation (invalid). E3's 16/20 came with a busy pinner thread holding the GIL during the kill, which
  stretched the late walk. Fix: the test stretches every walk by 20 ms through the `_win_descendants` seam (a
  loaded runner's walk); then 8/10 and 10/10 trials left survivors before the job.

## Log
- 2026-11-03: plan opened. Baseline on the untouched worktree: `test_run_suite.py` 185 passed in 38.5 s.
- Red light (16 failed, 182 passed, 87 s): the two `popen_kwargs` re-pins (0 vs 4, {} vs CREATE_SUSPENDED); the
  enumeration-failure test (now pins that the Windows grandchild dies too: it survived); S1/S2/S3 (grandchild
  survived each exited-root site); hard kill of the supervisor (the tree survived); spawn race (10/10 trials
  left the log locked); fallback (`AssignProcessToJobObject` never called); clean-exit hygiene (no job handle
  opened); kill-releases order (no release step); class 1 / class 3 / hygiene tree tests, the seam no-ops and
  the never-drains report (missing `attach` / `_jobs`).
- Items 1+2 (D1: CREATE_SUSPENDED, `attach` = job + assignment + resume, `_job`, `release` for a failed
  assignment, `supervise` attaches first): 186 passed, 12 failed (all waiting for items 3/4: the job was not yet
  terminated in `_signal`, its handle not yet released, no `reap`). Green: both re-pins, the fallback test and
  the hard kill of the supervisor (KILL_ON_JOB_CLOSE alone).
- Item 3 (`TerminateJobObject` first in `_signal`, `_verify` waits for an empty job, `-pid` marker, base
  `release`, `kill`'s finally releases the job after `close`): 191 passed, 7 failed (all need `reap` / the
  `finally`). Spawn race 10/10 trials clean, class 3 ended, handle hygiene clean.
- Item 4 (`reap` + `_reap_tree` at S1/S2/S3, `supervise` `finally: _TREE.release(proc)`): 198 passed.
- Item 5 (docstrings: `_ProcessTree` lifecycle and reach, `kill`, `_WindowsTree`, `_PosixTree` with E5 as a
  TODO): final run 198 passed in 44.3 s (baseline 185 in 38.5 s); spawn race 1.9 s for 10 trials.
- Nesting probe (scratch, not tracked): an outer `supervise` put a pytest child in its job (no breakaway, the
  pure lane's shape) and that pytest ran the 78 job / kill / cancel / supervise tests: 78 passed, rc 0, no
  "could not put pid" fallback, so nested assignment works here. windows-latest is still CI question 1.
- Other test files importing `scripts.run_suite`: none (`test_scripts/test_pytest_heartbeat.py` does not exist;
  `conftest.py` and `test_conftest_synthetic_fixture.py` only name it in comments). ruff: all checks passed.
