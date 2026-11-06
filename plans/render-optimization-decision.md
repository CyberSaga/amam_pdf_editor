# Render optimization: base-commit decision

## Current state and next step
- Owner request (2026-11-06): investigate optimizing from `33a70c4` versus returning to `0663a1c`, with every operation faster and no cross-operation regressions.
- Source investigation and runtime probes complete; recommendation: preserve `33a70c4` as the development base, replace the problematic scheduling policies, and retain the `thread` default until performance acceptance passes. [App performance v2](app-performance-v2.md) now schedules a budget-admitted two-worker integration profile and bounded hot-page DisplayList reuse, with one-worker/no-list controls. These are App candidates to validate, not accepted release defaults; direct clip remains deferred on pixel differences.
- This is a development-base recommendation, not a claim that the current process backend is faster overall. Both current choices fail the owner's overall goal.
- No product source, backend default, branch, or commit was changed in this investigation. Only this decision record and untracked diagnostic artifacts were added.
- NEXT: if implementation proceeds, first pin the measured cancellation/restart/readiness-fallback sequence with a failing integration test; then remove thumbnail contention and redundant raster work. Benchmark each file and operation separately against `0663a1c`.
- Existing `plans/perf-heavy-files.md` D6 permits up to 15% regressions. That allowance does not satisfy the owner's latest request and must not govern future acceptance.
- Formal whole-suite and all-operation performance acceptance remain open. No whole-suite restart was attempted.

## Decision and alternatives

Keep the worker/protocol, identity validation, lazy document source, lifecycle and failure-containment foundation from `33a70c4`. Change cancellation, transient-readiness fallback and the remaining in-App raster scheduling. A rollback removes useful infrastructure but restores the same in-process thumbnail bottleneck. It does not provide an alternative fast rendering engine.

The strongest argument for rollback is the current mixed performance, including noisier open timing in the new default thread path. We did not dismiss it: we exported the exact parent tree, ran its actual App against the current App, and separately removed thumbnail work as a diagnostic intervention. That intervention is not an acceptable product optimization by itself.

What would change this recommendation: a reproducible, isolated default-thread regression that cannot be corrected locally, or a persistent ready/non-restarting process that cannot meet time-to-content, GUI latency and memory budgets after contention is removed. No universal speed guarantee follows from the current data.

## Method and evidence

Artifacts: `_evidence_pilot/render-base-decision/` (untracked, not for commits).

- `run_compare.py`: 14 serial supervised actual-App runs; exit 0.
- `run_routing.py`: 3 further serial supervised actual-App runs; exit 0.
- Heavy PDF: three fresh App processes for each of `0663a1c/thread`, `33a70c4/thread`, `33a70c4/process`; order rotated across rounds. Exact parent source came from `git archive`, not a checkout/reset. All use the same main-checkout venv and PDF bytes under approved normal Windows permissions.
- Office PDF: one fresh App per configuration, only a diagnostic control.
- Thumbnail-disabled diagnosis: one run per configuration. This intentionally omits requested background work and cannot count as a speed acceptance pass.
- Rapid navigation: two additional thumbnail-disabled runs, one parent/thread and one current/process; End -> Home -> 125% without inter-navigation background drain. The process run includes routing trace.
- Same visible App, public file-open entry and QTest keys/combo input; high quality is required for the current target page. Normal sequence drains background after navigation. Open excludes worker handshake, which is timed separately. It is not cold-boot/CLI-immediate-open measurement.
- Readiness includes 50 ms stable confirmation; background idle includes 300 ms. Thus the approximately 301 ms thumbnail-disabled background result is a harness floor, not 301 ms of raster work.
- Diagnostic wrappers time GUI/model calls and in-App `Page.get_pixmap`, including worker-thread calls. They can change thread interleaving; do not compare these stall maxima directly to the earlier minimally instrumented report.
- `comparison-summary.json` contains medians/ranges for exactly r1-r3, excluding rapid-navigation and thumbnail-disabled samples.
- An initial sandbox run emitted temporary-directory cleanup PermissionError despite exit 0; it is excluded. All decision-table runs used normal Windows permissions. No permission shims were introduced.

### Heavy PDF: normal sequence, median of 3 (ms)

| Operation | 0663a1c thread | 33a70c4 thread | 33a70c4 process |
|---|---:|---:|---:|
| Open to current-page high quality | 1421.43 | 2098.05 | 3122.83 |
| End to high quality | 467.49 | 464.67 | 78.04 |
| 125% to high quality | 91.60 | 97.02 | 101.46 |
| Background after open | 35026.21 | 34974.72 | 31270.02 |
| Maximum processEvents call during background, median over runs | 4967.90 | 2740.63 | 3933.27 |

Open ranges: parent 1170.39-1754.95, current thread 812.56-4104.53, process 1742.61-4366.97. Three runs and substantial jitter do not establish statistical performance equivalence or a universal ranking. In particular, keeping thread as the default is not proof of parent-equivalent performance.

### Diagnostic thumbnail intervention (n=1, ms)

| Operation | 0663a1c thread | 33a70c4 thread | 33a70c4 process |
|---|---:|---:|---:|
| Open to current-page high quality | 583.49 | 600.05 | 449.00 |
| End to high quality | 453.31 | 439.08 | 76.34 |
| 125% to high quality | 91.13 | 91.92 | 96.77 |
| Background after open | 300.50 | 301.21 | 300.96 |

The intervention supports in-App thumbnail work as a major source of open contention and long background stalls. Current process mode still runs every clean-file thumbnail in `_ThumbnailWorker.run` (`controller/thumbnail_coordinator.py:52-75`); the source is shared with thread mode. This does not establish the exact share of the earlier 21.14-second stall or prove a future thumbnail implementation meets throughput goals.

### Rapid-navigation regression reproduced

`new-process-heavy-rapid-no-thumbs.json` records:

1. Worker ready, one start, document loaded; End and Home succeed.
2. During zoom, `RenderProcessClient.cancel` at 2037.10 ms calls `_dispose` at 2037.11 ms.
3. `start` occurs at 2058.11 ms with readiness false and document cleared.
4. `_start_worker` at 2079.91 ms sees readiness false; `_start_thread` follows at 2079.92 ms.
5. Child-start count is 2, but reported fallback count remains 0.
6. Zoom takes 280.80 ms versus 89.07 ms in the parent rapid sequence. Current process zoom after an explicit intervening drain takes 96.77 ms.

This confirms a real restart-to-QThread routing path associated with the reproduced slow zoom. It does not apportion the entire 191.73 ms difference among shutdown, startup, snapshot and thread raster work.

Source: active cancel unconditionally disposes/completes/restarts (`src/render_worker/process_client.py:192-201`); disposal includes a GUI-thread `waitForFinished(500)` (`:414-434`); coordinator requires backend readiness and otherwise starts a QThread (`controller/page_render_coordinator.py:198-222`). Its direct readiness fallback does not increment the metric that outcome-based fallback increments at `:265`.

## Proposed implementation order (not implemented here)

1. **Fix scheduling before migrating more callers.** Separate logical supersession from destructive cancellation. Coalesce pending work, discard obsolete results, retain a loaded document for short jobs, and reserve preemption for a defined latency budget. Starting/restarting must be distinct from unsupported/failed; a transient not-ready interval should retain the latest eligible request. Preserve save/close, stale identity and crash safety; count every actual backend route. Do not replace a blocking restart with unbounded waiting behind a dense render.
2. **Remove thumbnail contention.** Move clean and dirty eligible thumbnails out of the App process, prioritize visible-page and visible-thumbnail work, and bound background prefetch. Decide whether one worker is enough from visible-wait measurements; do not add processes/shared memory on assumption alone. Preserve overlays and dirty-state correctness. Report full thumbnail completion separately so deferred work cannot hide a regression.
3. **Reduce raster work, not just move it.** Measure persistent display-list/page-image caching across scales and navigation; key it by session, revision, page, annotations/profile/geometry and account for memory. Reuse the previous image as a temporary zoom preview while rebuilding the required continuous scene. A preview is not a high-quality completion. Cache and asynchronous first paint are candidate changes requiring independent evidence, not guaranteed wins.
4. **Cover remaining operations and failure paths.** Include cold and warm open, scroll, rapid zoom, Home/End, fullscreen, tab/window changes, dirty-document rendering, single-page/search navigation and watermarked documents. Some remain explicitly outside the old plan; the owner's broader goal requires measuring them and prioritizing their actual bottlenecks rather than assuming one raster change accelerates search/save/print/editing.
5. **Accept per operation and file.** Pair against the exact parent using the same machine/workload/quality and sufficient repetitions. Measure first feedback, full required-content completion, p95/tail input latency and total memory, under both settled and overlapping background workloads. Require no reproducible regression outside measured noise; require demonstrated improvement on the targeted slow operations. A geometric mean or an 80% End improvement cannot compensate for slower open/zoom. Do not enable process by default until the complete acceptance matrix passes.

## Review and limits

- Independent `deep-reasoner` source analysis agrees with preserving the foundation and repairing lifecycle policy; it initially marked causal attribution unverified. The subsequent routing experiment reproduced the readiness fallback.
- Independent `plan-code-reviewer` decision review could not start: `collab spawn failed: agent thread limit reached`. No further agents were spawned after that failure. Done-map: source analysis, 17 supervised App runs and decision record finished; final independent decision-document review not performed. This is a recommendation with that review limit, not full acceptance.
- No pytest/full suite was run: this is a read-only product investigation with measurement helpers, not a product patch. Full app acceptance remains open.
- No rollback, product change, default switch, commit or push was performed.
- Fence log: none; unrelated to_Update items were not changed.

## Running log

- 2026-11-06: checked both exact commits and existing raw measurements; established that earlier numbers were same-commit backend comparisons.
- 2026-11-06: completed 17 serial supervised visible-App runs, isolated thumbnail competition, and reproduced cancel -> restart -> direct QThread fallback during rapid zoom.
- 2026-11-06: recorded forward-optimization recommendation with explicit non-regression acceptance and uncertainty limits.
