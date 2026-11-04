# /simplify leftovers (2026-11-03): validator tables, run_suite kill path, sfnt + rederive measurements

## Current state / next step (keep under 40 lines)

- Started 2026-11-03 after the owner ruled on every owner-gated item of the 2026-11-03 TODOS section
  (「開始執行」). Base: the uncommitted /simplify pass on top of f84c9aa (7 files, all gates green; the owner commits).
- Status (2026-11-03, later the same day):
  M. measurements: DONE. sfnt corpus scan, MuPDF duplicate-tag experiment and rederive profile were judged and the
     owner ruled on both reports (D4 below).
  1. validator rule tables (a)-(d): LANDED and gated. VALIDATION.json byte-identical on all 24 `*_r2` batches, the
     rederive report on `20261102_0952_r2` identical after masking `remeasured.output_sha256`; contract tests 642
     passed, rederive 302. ARCHITECTURE / PITFALLS / TODOS ticked (see the Log entry).
  2. `run_suite.py`: step (i) characterization tests DONE; step (ii) refactor DONE (`test_run_suite.py` 185
     passed; S6 edited ARCHITECTURE 7.4, PITFALLS, TODOS); step (iii) local part DONE (full suite 9593 passed /
     0 hung / 0 crashed; external-kill drill killed on stall, rerun OK, no orphan). CI is the only open step: it
     needs a push, which only the owner does; the ubuntu cell is advisory, so its result must be read by hand.
  3. sfnt lane (steps 1-7, D4): DONE and archived (`plans/archive/sfnt-directory.md`); corpus gate = 3 R2 flips
     (2 ttcf + issue2537r via the loca_format rule, an open owner decision in TODOS). rederive candidate 1: DONE
     (0 report differences on two batches; 4.3 s saved on the designated pair, 5.45 s over three runs).
- Next step: owner commits the 22 paths in one commit (bundle + rederive are inseparable) and pushes / opens a PR
  for CI; owner rules on loca_format and on keeping candidate 1 at 4.3 s; then M2 as its own item.
- Decisions:
  - D1 characterization-first for item 2 is the owner's ruling (2026-11-03) and overrides the red-light-first rule
    for that item; the red test for the probe-cancel gap is written as a red test after the characterization block.
  - D2 no worktree isolation for agents: a worktree checks out HEAD and drops the uncommitted /simplify files.
    Items 1 and 2 touch disjoint files, so they run in the main tree, sequentially, tests in the main session.
  - D3 HUNG/FAIL labels and evidence timing may change in item 2 (owner), hang detection must not.
  - D4 (owner, 2026-11-03, after the measurements): sfnt = the four measured rulings (first in-range entry, every
    head >= 54, ttcf refused in both readers, out-of-range entries dropped with hmtx clipped / hmtx offset fatal;
    R1 cmap/post out of range = absent), memory release included, scanner promoted to `scripts/`, M2 as a TODO;
    rederive = candidate 1 only, an `at_head` change caused by the dropped pre-serialisation lands as a parity fix,
    4 rejected, 2 and 3 deferred, 5 a TODO for Grok. Recorded in TODOS.md items 6, 9, 10.
- Dead ends: none yet.

## Log

- 2026-11-03: rederive candidate 1 LANDED (`_prepare_located`, `_Scene.whole_locate_info`, `_run_probe` on the
  scene's frame/locate; `frame_prepare` self-contained for the standalone caller). P1 shadow 196/196 (0952) and
  179/179 (1751), P2 masked diff 0 on both batches with equal exit codes, P3 rederive 305 / frame parity 5 /
  real-corpus acceptance 51, P4 0952 46.1 -> 41.8 s on the designated pair (4.3 s; 5.45 s over three runs),
  1751 43.1 -> 35.9 s. Opus review: matches the design (notes only; ARCHITECTURE probe wording updated).
- 2026-11-03: final whole-tree gate on the finished tree: code graph re-indexed; `ruff check .` clean; mypy
  Success (82 files); VALIDATION.json byte-identical on all 24 `*_r2` batches; 0952 rederive report identical
  after masking; `scripts/run_suite.py`: 9593 passed, 0 failed, 17 skipped, 0 hung, 0 crashed, 1 rc5-ok in
  2331.6 s (was 9375 passed before this work). External-kill drill (temporary untracked test file, one pass +
  one real hang with a python grandchild, `--stall-seconds 5`): `HUNG 10.0s (killed on stall after 10.0s; hang in
  ...::test_drill_hangs_with_a_grandchild; rerun once with --deselect)`, `rerun without ... OK 0.3s`, no
  "not gone after the kill" warning, test pid + grandchild launcher + grandchild python all gone afterwards
  (listing only), evidence heartbeat + tail written; drill file deleted, `git status` clean of it. Step (iii)
  local part done; CI (owner push; read the advisory ubuntu cell by hand) is the only open step.

- 2026-11-03: validator rule tables (a)-(d) LANDED in the tree (code + contract tests; docs/TODOS tick pending):
  `RULE_SINCE` (12 rules) + `_since`, `REVISION_SCHEMA` + kinds, `R0_SITES` (5 classes; SitePin / KwargsPin /
  R0Site) with the retired-branch equivalence grids, `BATCH_SCOPED_CODES` (18 codes, beside REQUIRED_BATCH_FILES,
  subset test replaces locality); rederive reads `eb._since` and unions `eb.BATCH_SCOPED_CODES`. Contract 642
  passed (616 + 26), rederive 302. Byte gate: VALIDATION.json byte-identical on all 24 `*_r2` batches; the 0952
  rederive report identical after masking `remeasured.output_sha256` (0 differences, 91 results). Opus review:
  matches the specs. Deviation: R0_SITES sits after RULE_SINCE, not after KSIGN_SITE_PIN_REV.

- 2026-11-03: plan opened; advisor review of the lane layout (keep validator -> run_suite, measurements first,
  no worktrees, CI is the owner's step). Measurement workflow launched; validate baselines started.
- 2026-11-03: validate baselines for the 24 `*_r2` batches written (scratchpad `m1/vbase`); a second run of two
  batches is byte-identical, so the gate is sound.
- 2026-11-03: measurement workflow done (5 agents, 30 min). sfnt: corpus 4,401 PDFs / 3,477 programs; duplicate
  tag 0, head < 54 0, ttcf 2 (issue13193, issue9262_reduced), out-of-range 2 (bogus tag, no effect); MuPDF measured
  pixel-exact: first in-range directory entry wins, every head entry must be >= 54, out-of-range optional tables
  are ignored, hmtx length clipped / offset past EOF fatal, ttcf loads face 0 by file-absolute offsets (R2's
  member-relative rebase misreads both corpus programs). Judge: one fitz-free `sfnt.py` following the measured
  rules, ttcf refused in both readers; 5 owner questions (ttcf, R1 cmap/post out of range, M2 follow-up
  measurement, memory-release step, scanner promotion); reports in scratchpad `m1/sfnt_decision.md`,
  `sfnt_scan.md`, `mupdf_dup.md`. rederive: 91 cases, 48 s; candidate 1 (`frame_prepare` re-serialises per
  call, 196 calls, 5.4-7 s) is the only one worth a diff cycle; 4 and 5 rejected, 2 and 3 deferred; one risk:
  the probe doc is no longer serialised before `engine.prepare` (PITFALLS tobytes-KEEP reorder); report in
  `m1/rederive_decision.md`, `rederive_profile.md`. Both wait for owner rulings.
- 2026-11-03: run_suite step (i) DONE locally: 23 characterization tests appended to `test_scripts/test_run_suite.py`
  (section "characterization (2026-11-03, kill path, owner step 1)"; real-process cancel / Ctrl+C / kill-tree /
  parallel-lanes orphan tests, Popen flags per platform, py-spy targets, /proc and ps walkers, timing-order guard
  540 < 600 and CI ceiling <= default, probe paths/env, stale cleanup, evidence location vs CI upload globs);
  155 passed in 29 s (was 132). POSIX branches run only on the ubuntu CI cell. Audit findings for step (ii):
  F1 `_kill_tree` re-enumeration drops already-known members without CloseHandle (one handle leaks per live
  member on every Windows kill; the docstring and TODOS line 5 claim otherwise); F2 the cancel/Ctrl+C handler
  discards the survivors list (no warning); F3 the window between Popen and the try is unguarded; F7 POSIX
  kill depends on start_new_session. Red tests for step (ii): probe cancel (required), handle leak (F1).
  Refuter corrections on the design recorded in scratchpad `m1/rs_refute.json` (handle-counter test, bounded
  probe timeout, killpg reaches the group only, exception-safe late-member close, probe log contract, env).
- 2026-11-03: run_suite step (ii) S1 `_supervised_pytest(spec, kind, ...)`: `RUN`/`PROBE`, frozen `_ChildPaths` and
  `SuiteTiming`; run and probe children share paths, stale junit/heartbeat cleanup and the clean env;
  `collect_probe` signature unchanged. 162 passed.
- 2026-11-03: S2 one timing resolution: `DEFAULT_STALL_SECONDS`/`DEFAULT_FILE_CEILING`/`DEFAULT_POLL_SECONDS`,
  `SuiteTiming.from_args`, `main` resolves once and `_run_jobs` unpacks it into `run_job`'s flat kwargs. 166 passed.
- 2026-11-03: S3 probe cancellable: `collect_probe(cancel=)`, `_supervised_pytest` raises `JobCancelled` before any
  spawn when cancel is set; a probe in flight dies at its next poll and raises (never -1). 170 passed.
- 2026-11-03: S4 `_ProcessTree` part A: `_WindowsTree`/`_PosixTree`, `_TREE` chosen at import; Popen kwargs,
  enumeration, py-spy targets and close moved in; `_descendants`/`_close_members` kept as delegates. 173 passed.
- 2026-11-03: S5 part B: `_ProcessTree.kill` template (late members, signal, `proc.kill`, wait, root poll, verify,
  close in finally); `_kill_tree` a one-line delegate; no function body reads `sys.platform`. 178 passed.
- 2026-11-03: S6 duplicate-handle fix: every Windows kill leaked one duplicate handle per live member (fresh
  enumeration filtered known pids without CloseHandle). `_add_late_members` now extends targets with the whole fresh
  list in one statement and then closes the known-pid duplicates; red tests use a live per-handle counter (three
  handles open before, none after). F2: the `supervise` exception handler logs `_kill_tree`'s survivors. F3: the
  lines after `Popen` moved inside the `try`. ARCHITECTURE 7.4, a PITFALLS entry (with the residual orphan classes)
  and TODOS (items 8, 12, 13 ticked, line-5 claim corrected, one new owner-gated item) updated. 185 passed.
  Step (iii) (full `run_suite.py` run, CI) is next and the owner's to gate.
