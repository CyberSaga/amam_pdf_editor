# App performance v2: evidence-gated optimization

## Current state and next step
- Status: concrete integration plan informed by isolated measurements. Implement an opt-in, budget-admitted two-worker profile and bounded hot-page DisplayList reuse; release/default admission still requires real App evidence. Direct clipping remains deferred on pixel counterexamples.
- Scope: all local App operations, using `33a70c4` as the implementation base and `0663a1c` as the comparison baseline.
- Owner choices retained: slow operations improve at least 20%; fast operations do not measurably regress; combined App/child memory increases by at most 300 MiB for the same workload.
- This plan supersedes the execution policy in `perf-heavy-files.md`, including its old regression allowance, one-child restriction, and exclusions of low paint, watermarks, search and preview. Historical measurements remain evidence, not new acceptance results.
- Full-suite execution remains owner-paused. No product edits, backend-default change, commit or rollback is authorized by this planning deliverable itself.
- Isolated feasibility runs are complete: 12 pool configurations, 88 clip observations, 44 DisplayList comparisons and 6 clip controls. These support integration work, not a claim that the configuration is optimal or release-ready.
- NEXT: freeze comparison contracts/reservations in M0, fix lifecycle in M1, route raster in M2, integrate the two-worker profile in M4, then add hot-page reuse in M3. Test each delta separately before their combination. M6 bottlenecks may take priority when attribution demands it. No product implementation or default change was made in this planning revision.

## 1. Outcomes and release gates

Twenty percent is the minimum improvement for a slow operation, not the optimization target. Reduce total work first, then use parallel capacity to meet explicit time budgets. A faster End command cannot compensate for a slower open, edit, save, or thumbnail sweep.

| Metric | Target / gate |
|---|---|
| Every operation whose baseline completion is at least 100 ms | At least 20% faster, separately for each file, state and operation |
| Faster operations | No measurable regression; freeze the A/A noise bound before comparing candidates, at most 5 ms |
| Input acknowledgement / event-loop response | p95 at most 50 ms; maximum observed at most 150 ms in the specified workload |
| Warm navigation/zoom: current visible content at required high quality | p95 at most 250 ms, including queueing, transport, image application and paint |
| Cold App file-open command to required high-quality viewport | p95 at most 1 s; maximum observed at most 2 s; include worker startup when not already ready |
| Complete post-open work, HVAC 50 pages | At most 15 s in the fixed idle workload |
| Complete post-open work, heavy 90 pages | At most 20 s in the fixed idle workload |
| Combined simultaneous App + all owned child RSS | At most baseline peak + 300 MiB for the same workload; also report private commit, available RAM and paging |
| Shutdown / error path | No leaked process or reader; bounded asynchronous completion; correct document state |

These are targets that must be demonstrated, not predictions. A miss stays visible and prevents calling the overall optimization complete. A resource-pressure fallback has its own measurements and cannot be averaged into the normal profile.

Freeze these endpoints before changing rendering:
- First feedback, first actual target-content paint, required-quality visible completion, operation completion, and full background completion are separate timestamps. A placeholder is feedback, not target content.
- Progressive refinement is explicitly allowed. A stale/low-resolution preview never satisfies required-quality completion.
- Background completion requires all expected thumbnails at the existing dimensions, color/annotation policy and current revision, plus the same required indexing/metadata work as the baseline. Empty queues, deferred work, or disabled thumbnails are insufficient.
- For tiles, visible completion means every required visible tile is painted. Report full-page and background completion separately; do not compare a viewport-only milestone with the old full-page milestone and call it an equivalent speedup.
- Eliminate the diagnostic 50 ms readiness and 300 ms idle floors from operation durations; log stability checks separately.

## 2. Measurement and the GLM review

Use the measured pool throughput and page-specific DisplayList gains to select bounded App integration candidates: start with two compute workers and hot-page reuse, then compare them against the single-worker control. Integration eligibility is distinct from release/default admission. Four workers remain a diagnostic comparison, and direct clipping remains deferred because sampled pixels differ.

Corrections that govern the experiments:
- The old censored background result of at least 120 s and the later 31-35 s targeted diagnostic come from different harnesses/workloads. Neither proves that a particular threefold excess is scheduler overhead.
- The clip probe always draws the whole page first and the clip second. It measures different areas with asymmetric warming. Its ratios, including an estimated 2-5x, are hypotheses rather than App speedups.
- Four workers give an ideal parallel bound, not fourfold acceleration. Document interpretation, duplicated native caches, startup, IPC, CPU contention and GUI application remain costs.
- A 144 MiB single-child peak does not establish that four children fit the owner's extra 300 MiB allowance. Free system RAM and the App's incremental budget must both pass admission.
- 300 ms does not pass a 250 ms target. A few End samples do not establish either p95 or cold-open performance.
- The existing 224 passing focused tests cover the shipped transport/integration, not the proposed pool, tiles or new caches.
- Continuous scene rebuilding currently creates placeholders and schedules visible rendering; it does not raster every page.

Record timestamps for document load, snapshot production, display-list construction, raster, IPC encode/write/read, GUI conversion, scene application and paint. Also record jobs submitted/coalesced/cancelled, wrong-generation results, fallback reason, child restarts, document loads, display-list hits, bytes and simultaneous memory. Track CPU time and paging so a lower RSS cannot hide swapping.

### 2.1 Controlled feasibility evidence (2026-11-06)

Artifacts: `_evidence_pilot/perf-hypotheses/summary.md`, `raw.json`, `clip-control.json`, `manifest.json` and supervised logs. These are exploratory measurements, not App benchmarks. The manifest records input/artifact hashes and Python version; PyMuPDF is 1.27.1.

**Pool:** all pages at the current thumbnail scale, RGB/annotations retained, full sample bytes returned over IPC and copied to parent QImages. All thumbnail hashes matched across counts and both sweeps. One configuration run per file/count, not repeated statistical acceptance. First sweep includes child startup/document load; second sweep reuses the pool but dynamic scheduling does not establish per-page warm-cache affinity.

| File | Workers | First sweep seconds | Second sweep seconds | Sampled parent + children RSS MiB |
|---|---:|---:|---:|---:|
| HVAC, 50 pages | 1 | 51.18 | 48.85 | 411 |
| HVAC, 50 pages | 2 | 23.87 | 27.35 | 623 |
| HVAC, 50 pages | 3 | 18.70 | 21.16 | 777 |
| HVAC, 50 pages | 4 | 13.85 | 16.01 | 821 |
| Heavy, 90 pages | 1 | 65.35 | 61.66 | 481 |
| Heavy, 90 pages | 2 | 54.37 | 34.65 | 800 |
| Heavy, 90 pages | 3 | 29.89 | 33.52 | 1147 |
| Heavy, 90 pages | 4 | 28.80 | 24.82 | 1452 |

Office first sweeps were 1.230/0.587/0.518/0.589 seconds for 1/2/3/4 workers: this single observation does not support selecting four for startup. Heavy's two-worker first sweep improved only about 17%, and three-to-four-worker first-sweep improvement was about 4%. These exploratory numbers do not select an optimal count.

RSS values are simultaneous sampled observations, not summed lifetime peaks or measured allocation bounds. Submission/copy/hash creates sampling gaps; parent retention and configuration order also confound memory differences. Office/HVAC shared one probe parent; heavy used a fresh parent after the first supervisor interruption. No configuration has demonstrated the real App's baseline +300 MiB gate, startup, foreground latency, indexing or competing-helper behavior. Do not translate a thumbnail-only sweep into full App background completion.

**Clip:** 11 sampled pages across office/HVAC/heavy, four repetitions per cold/warm cohort, fresh document per method, alternating full/clip order, 2x scale and a central ten-percent-height band. Document opening/page acquisition is excluded. On heavy pages 45/46, cold full/clip median ratios were only 1.39/1.37; warm ratios were 3.28/3.09. A universal 2-5x App gain is unsupported.

Only 64/88 clip observations were bit-identical to equal-scale full-page crops, also 64/88 with a two-pixel inset. Six additional controls used fresh documents, the same central band at 2x scale, and fixed full-A/full-B/clip/halo order with no pre-raster warm-up; they check pixels only and their timings are not combined with performance cohorts. Full/full matched in all six. HVAC page 25 direct clip differed in 2037 RGB channels (maximum difference 63); the sixteen-pixel halo still differed in 777 channels (maximum 5), repeated twice. Page 26's halo restored equality; heavy page 45 matched directly. This establishes sampled raster differences, not a claim of visible missing content. A halo is not yet a general correctness solution; direct clip is not admitted.

**DisplayList:** 44 paired comparisons, including list creation in cold timings and three repeated rasters per warm measurement; all paired pixel hashes matched. HVAC pages 25/26 warm medians fell from 404/604 ms to 283/366 ms, while heavy pages 45/46 stayed about 267/303 ms. HVAC page 25 cold timing including list creation was 465 ms versus direct Page 455 ms. This supports a bounded repeated-use candidate, not universal gain, first-render improvement or App cache/invalidation/memory acceptance.

**Disposition (revised after the owner's follow-up):** implement the smallest useful App candidates rather than treating missing App evidence as a prohibition on integration. M4 specifies the initial two-worker profile; M3 specifies the hot-page cache and its limits. These are conservative starting policies to validate, not measured optima. Three/four workers are explicit diagnostic configurations only; direct clip/universal halo remains excluded. Default rollout requires the equivalent-quality App evidence in M7.

### 2.2 Selected starting policies

| Component | Initial implementation | Explicit boundary |
|---|---|---|
| Normal opt-in process profile | Up to two compute children across the App; one foreground slot, one background slot | Resource admission can retain one worker; no unmeasured automatic expansion to three/four |
| Extra worker startup | Lazy, after first required-quality visible paint and only while useful work remains | No extra child/document load on the initial file-open critical path; measure total background completion too |
| DisplayList retention | After initial required-quality paint, promote on a repeated foreground raster cache miss for the same immutable page; at most one retained list per worker and two App-wide | Existing Page path on first use; low/high phases of the same initial intent do not trigger promotion; no retention for a one-pass background thumbnail sweep; count promotion cost |
| Larger pools | Explicit 1/2/3/4 diagnostic comparison after lifecycle/resource instrumentation works | No default three/four-worker profile or memory-budget increase from isolated throughput numbers |
| Clip/tiles | Keep full-page raster in the implementation sequence | Resume only after corrected clip quality passes; do not silently accept the current pixel differences |

The two-worker and two-list caps are starting implementation bounds, not experimentally established optima or guarantees that memory fits. M0 must first measure conservative document/list/frame reservations; unknown headroom means one worker and no retained lists until qualified. The global +300 MiB budget is unchanged.

## 3. Implementation milestones

### M0. Freeze equivalent work and benchmarks
- Inventory startup, clean/dirty/encrypted open, Home/End/jump, rapid navigation, zoom, scroll, fullscreen, tabs/detach, search, text preview/apply, Undo/Redo, structural edits, save/save-as/reopen, print preparation, local OCR preparation, tab close and App shutdown.
- Use office, HVAC and heavy documents, plus generated mutation/encryption/overlay fixtures. Run cold-process/warm-process and cold-document/warm-document cases separately; do not claim an OS cold boot from a fresh App process.
- Establish reproducible A/A noise and capture the exact baseline operation/quality contract. Test both idle-background and interactive-background workloads. Preserve timestamps and per-file results instead of a single aggregate score.
- Before pool expansion, give every slow operation a cost breakdown, a concrete candidate change and its correctness test, or an explicit unresolved feasibility result. Serialization/model-mutation bottlenecks enter M6 before further render tuning when they dominate. Merely listing save/Undo/edit in the matrix does not establish a speedup.
- In an isolated child, benchmark direct Page versus persistent DisplayList, and full-page versus clip at the same scale/DPR. Alternate A/B order with fresh documents and separate cold/warm cohorts. Include the densest page, not only the favorable page.
- Reuse the completed isolated measurements rather than rerunning them unchanged. Before expansion/retention, measure conservative native document/list and in-flight frame reservations in the instrumented one-worker App; include transport copies and dying children. Unknown reservations disable the optional expansion/cache. Freeze controls for one-worker/no-list, two-worker/no-list, one-worker/list and two-worker/list; larger pools are a later diagnostic cohort.

### M1. Stop cancellation from destroying useful state
- Separate logical supersession from process termination. Drop stale queued work and stale results without restarting a healthy child on every key or zoom.
- Represent starting/ready/busy/draining/failed explicitly. Transient not-ready requests wait asynchronously; they do not silently switch to a GIL-holding QThread.
- Preserve required visible jobs while coalescing obsolete viewport intents. Keep a bounded current foreground set and a bounded background queue.
- Permit physical preemption for a stuck or blocking job using measured remaining-work versus restart/load cost. Termination/reaping goes through the QProcess lifecycle, not a GUI-thread wait.
- Regardless of worker count, when all render capacity is busy with obsolete/background raster, a foreground request waiting 150 ms triggers asynchronous recall/abort of the job occupying or borrowing foreground capacity, unless it already completed. Do not start its replacement until the old child has exited and the replacement reservation fits. The 150 ms bound starts recall; it does not guarantee the replacement image is ready then, and restart/load time remains in the visible-completion gate. Keep the last valid preview and explicit pending state; memory pressure never silently selects in-App raster. Active atomic edit/save/print transactions use their own bounded transaction/cancellation contract instead of this raster-abort rule.
- Keep crash containment, page quarantine and a bounded fallback. Count startup, readiness, timeout, oversize and quarantined fallbacks separately. An unchanged oversized request is not retried indefinitely.
- Gate: rapid End -> Home -> zoom cannot reproduce restart -> not-ready -> uncounted-thread fallback. A healthy navigation sequence must not incur repeated document loads.

### M2. Remove remaining raster work from the App process
- Route immediate low/high visible paint, clean and dirty thumbnails, single-page mode, search-result jumps and watermark-aware rendering through the service.
- Foreground visible pages precede visible thumbnails; background thumbnails/prefetch get bounded service so they still finish. Avoid head-of-line blocking across detached windows.
- Render watermarks/overlays on an immutable purpose-specific worker view; preserve base-document bytes and avoid applying an overlay twice.
- Keep a correctly positioned existing image or a low-resolution preview during refinement. Cache-hit fast paths must remain synchronous and cheap.
- Gate: no ordinary page/thumbnail raster in the GUI process in healthy process mode; every exception is enumerated and timed. Full-thumbnail completion must improve as well as interaction latency.

### M3. Bounded hot-page DisplayLists, snapshots and pixels
- Keep loaded documents in their owning worker. First use keeps the existing Page raster path. After initial required-quality paint, a repeated foreground raster cache miss for the same immutable page may build/retain its DisplayList only if the measured native-memory reservation fits. Pixel-cache hits need no list, and low/high phases of the same initial viewport intent do not trigger promotion. Count this promotion/build in operation time; the isolated warm-render gain does not prove promotion is free or profitable on the first revisit.
- Retain at most one DisplayList per render worker and two across the App in the initial profile. Prefer the current visible/repeatedly zoomed page; evict unpinned least-recently-used entries. Do not retain a list for a page visited only once in the background thumbnail sweep. This applies by request behavior, not an HVAC filename or page-number whitelist.
- Reuse the retained list across scales/DPR and eligible thumbnail requests with the same source/annotation/overlay contract; keep scale/DPR/color-specific pixel cache keys separate. Key the list by immutable source/content identity, page geometry and annotation/overlay inclusion; invalidate changed identities before reuse. Preserve document affinity so repeated requests can reach the owner of the list.
- Bound all existing raster/list caches with an App-wide ledger, including exact frame/image bytes, conservative measured native-list/document reservations and RSS/private-commit feedback. Refuse retention when the combined budget cannot be reserved; eviction does not prove native RSS was returned. Never double-count allocated resident bytes and their prior reservation.
- Native objects never cross processes. Pin an entry while a job uses it; evict dependent entries before releasing their document. Keep document affinity when it avoids repeated parse/transfer work.
- Snapshot once per immutable content version, not once per request or keystroke. Cache purpose-specific representations rather than interchanging undo, worker and print bytes.
- Maintain distinct identities: content generation advances for semantic document mutations (including invisible OCR); render revision advances when visual output is invalidated; xref epoch advances when reference numbering/handle validity changes. Save maintenance and mutations before failed save invalidate affected derived artifacts. Every reply validates current session/owner, content and render identity, geometry, purpose and overlay state before GUI application; xref-sensitive plans additionally validate the xref epoch.
- Refresh purpose-specific snapshot metadata when session/maintenance state changes even if reusable serialized content is unchanged. A byte-cache hit does not preserve stale undo/security/version metadata.
- Preserve undo's DocSnapshot metadata and encryption policy, worker-view decryption/overlay policy, and print's secure-save-required orphan pruning. A shared cache never substitutes one purpose's bytes for another's required representation.
- Reuse across Edit -> Undo only when validated page contents, reachable resources, geometry, annotation/overlay fingerprint and xref epoch match. Unknown dependencies cause a miss. A reused raster still receives the current request identity; an old token never becomes valid again.
- Batch/pace image application under an 8 ms GUI work budget, with bounded in-flight frames. Try smaller frames/tiles before adopting shared memory; add shared memory only if measured copies remain a material bottleneck and its ownership/cleanup is proven.
- Gate: lower parse/snapshot counts, unchanged pixels, no repeated content hashing of the whole document per frame, and global memory acceptance across multiple controllers.
- Compare the no-list and hot-list App paths on first render, promotion, repeated zoom, pan, revisits, Edit/Undo/Redo and save/reopen. Keep no-list behavior for measured losing workload classes or revise the promotion policy; a cache hit-rate gain alone is insufficient. Do not claim a universal 30-39% App speedup from the sampled HVAC render timings.

### M4. Integrate a two-worker profile, with one-worker control
- This is the first concrete App pool configuration, not a declaration of optimality. Normal opt-in process mode admits at most two compute children across detached windows/controllers and print/preview/operation helpers; all children count toward memory. Retain one renderer when the second reservation does not fit. Adding a print/helper job drains or retires the background slot asynchronously before admitting its replacement; it does not create an unaccounted extra child.
- Start the first worker for required visible work. Start the second lazily after first required-quality visible paint, recheck that useful work remains before document loading, and reserve a foreground slot. When no foreground work waits, both slots may serve background work, but a borrowed foreground slot must follow M1's 150 ms recall rule for every worker count, asynchronous exit and replacement admission. Test a foreground arrival during two long background rasters explicitly, including restart/document-load cost; if borrowing fails visible-latency gates, retain the foreground slot rather than hiding the regression in faster background totals. Background work may not monopolize the only worker in degraded mode.
- Prioritize visible page -> visible thumbnails -> remaining thumbnails/prefetch with bounded background progress and document affinity. Coalesce obsolete intents without restarting healthy children; send each page job once for its identity and reject stale replies through the existing tuple checks.
- Admit before startup, snapshot capture, document load and raster allocation using M0's measured conservative reservations. Count terminating children until actual exit, and preserve sufficient system headroom. On pressure stop new background assignments, evict eligible caches and retire idle children asynchronously; do not block the GUI or cancel an active atomic mutation to free a slot.
- Compare fixed one/two-worker modes with lists disabled first. Then compare one/two-worker modes with M3 enabled. Separately measure initial paint, complete background work, interaction during background work, multiple windows, failure paths and simultaneous App/all-child memory. Report one-worker fallback frequency and performance; it cannot be averaged away.
- Keep explicit three/four-worker diagnostic options in the same scheduler for later equivalent-work comparisons, subject to the same reservations and global budget. They are not automatic modes or defaults. If two fails a target, publish the miss and test the larger configurations rather than declaring two sufficient; if no configuration passes both speed and memory, leave acceptance open and reduce duplicated interpretation/bytes before reconsidering the resource policy.
- Gate: choose a rollout configuration only from real App results satisfying every operation/resource gate. Do not relax +300 MiB, tolerate a slow open, or translate thumbnail-only throughput into App acceptance to force a pass.

### M5. Reserved: no admitted clip/tile policy
- Do not implement the direct-clip shortcut from its raster timings. Sampled HVAC pages fail exact pixel comparison, including one case with a 16-pixel halo. Admission requires a corrected equivalent-quality App experiment, not the existing multiplier.

### M6. Speed the other local App operations without weakening semantics
- Attribute remaining slow search/index, preview/verify, structural mutation, snapshot/save and print/OCR preparation to their actual costs. Add caches, incremental work or offload at the Model boundary, rather than accelerating only the view.
- A worker reads an immutable document version; it never shares a live fitz.Document with the GUI. Mutations remain serialized. Return explicit immutable results/PatchSets and validate their source identity before applying.
- Preserve exact preview -> PreparedEdit -> Apply candidate reuse. Any IPC schema is explicit and bounded; no pickle and no cheaper substitute for fidelity verification.
- If serialization or a native mutation still blocks the GUI beyond budget, move ownership of that document's Qt-free engine into a persistent operation host. Use versioned commands, immutable results and existing atomic/undo transaction semantics; do not repeatedly serialize the same live document to hide the ownership problem. Count this host in M4's App-wide compute limit and the global baseline +300 MiB ledger; background render capacity yields to the operation transaction.
- Save waits asynchronously for every worker reader to release the relevant version/path. Cover save failure that already changed page state, encryption/passwords, signatures, secure-save pruning, recovery and cancellation. UI feedback can be immediate; successful completion requires the real durable result.
- Print-preparation completion includes snapshot production and the helper's remaining local work through submission to the spooler/device boundary. The earlier `prepared` signal alone is not completion; external hardware/service waiting is identified separately.
- Gate: the full operation matrix passes, including Edit -> Undo -> Redo -> Save -> Reopen and detached-window operations. Printer hardware and external OCR/service latency stay outside the local performance claim.

### M7. Acceptance, review and rollout
- Write and demonstrate a failing test before each implementation milestone. Run only affected test files serially, plus ruff/types/import contracts as appropriate.
- Verify the actual App through its public entry and normal UI actions with QTest, screenshots and save/reopen; run drivers under `scripts/verify_supervise.py --stall 120 --ceiling 900`. Preserve font/scale/origin and unchanged-neighbor fidelity through preview, Apply, Undo/Redo and reopen. Use a measurement-light run for timing and a separate diagnostic run for attribution.
- Separate exploratory tuning from acceptance. After choosing the policy, freeze code/configuration and collect twenty fresh paired baseline/candidate sessions per required case, alternating order. Use one final inferential look, not an ordinary 95% interval at ten runs followed by conditional extension. A slow operation passes only when the upper 95% confidence bound of its duration ratio is at most 0.8; fast-operation bounds must fit the frozen A/A margin. An inconclusive result is unproven, not passed.
- A p95 claim needs at least 100 complete operation observations across at least twenty independent App sessions in the defined cohort; each cold-App observation requires a fresh App instance. Treat the App session as the experimental cluster; estimate the tail and its confidence bound with session-level resampling rather than pretending commands in one session are independent. The upper bound must meet the target. At least 1,000 GUI latency probes are a separate dataset and cannot substitute for operation samples. Maximum means the observed maximum over this workload, not a universal guarantee.
- Require every run's full-background workload to meet its absolute budget; report interactive contention separately. Stop on sustained paging or memory pressure and retain the partial result.
- Fault matrix: startup delayed, crash, bad/partial frame, timeout, oversize, rapid supersession, stale revision, low memory, save/close during work, multiple windows and App shutdown. Preserve explicit correctness fallback; do not claim normal performance when it is active.
- An independent plan-code-reviewer checks each multi-file milestone before completion. Update architecture/pitfalls/index/TODOS with implementation; retain test/evidence paths and known limitations.
- The full suite remains paused until the owner resumes it. Default remains thread until all required correctness/performance gates, including the resumed full suite, pass. Retain a bounded opt-in process rollout and a supported fallback.

## 4. Delivery and delegation
- Main implementer owns integration and the serial benchmark lane. Use one reader for a bounded source inventory when needed, then one reviewer after the milestone; do not run tests or benchmarks concurrently across agents.
- Execution order: M0 -> M1 -> M2 -> M4 two-worker integration -> M3 hot-page reuse -> M6 -> M7. M6 moves earlier when attribution identifies a dominant non-render bottleneck. M5 remains deferred. Deliver each as a separately reviewable change and measure the independent deltas before the combined profile. After each, publish the same per-file operation/background table, memory and fallback counts. A later gain never erases an earlier unresolved regression.
- Preserve the current transport/protocol/lifecycle foundation. Do not revert to `0663a1c` or change the default to disguise a failing candidate.
- Product feature changes, printer-driver tuning, external service performance, dependency upgrades and whole-suite restart are outside this plan's immediate execution scope.

## Running log
- 2026-11-06: prepared a replacement after the owner's GLM review. Read the actual clip probe, current cancellation/readiness paths, raster functions, memory sampler, preview-candidate and print-helper contracts. Existing comparison artifacts remain diagnostic; no new speedup was measured in this planning pass.
- Independent plan-code-reviewer challenged feasibility-first selection, non-render critical paths, allocation-time reservations, foreground service with one worker and configuration-selection/statistical bias. A second pass required cold-open p95 and explicit version-advance contracts. Final delta review: ship, no remaining concrete planning blocker; implementation/performance acceptance remains pending.
- 2026-11-06 owner requested empirical confirmation before admission. Isolated pool/clip/DisplayList runs completed and the proposed pool/tile policies were removed from the implementation sequence. First driver was interrupted by the 120-second no-output supervisor rule after completing office/HVAC, not by a demonstrated native hang; added incremental progress and resumed only the unfinished heavy pool cases. Region run exit 0 (125.8 s), controls exit 0 (11.2 s), heavy resume exit 0 (334.3 s). Initial DisplayList output reused the `page` field for metrics and lost its numeric position; the summarizer recovers position from the validated paired clip record, without changing timings. Probe-only code requires no product regression tests or product TODOS completion entry; no product behavior changed and the full suite remains paused.
- Independent evidence/plan review required truthful second-sweep and sampled-RSS labels, explicit parent/order caveats, pre-measurement contract freezing and removal of a dangling M4 resource-limit reference. Corrected those findings; the complete table is one exploratory pass over all twelve configurations, not the earlier partial snapshot. Control timings remain separate from the alternating cold/warm performance cohorts.
- Owner follow-up clarified that measured benefits should lead to concrete implementation scope. Revised the overly restrictive integration exclusion: schedule a budget-admitted two-worker App profile and behavior-based hot-page DisplayList cache (one per worker, two App-wide), with one-worker/no-list controls and optional larger-pool diagnostics. These are testable starting policies rather than claimed optima; release/default acceptance, unchanged +300 MiB budget, paused full suite and direct-clip exclusion remain in force.
- Independent delta review found that allowing background work to borrow both slots lacked a multi-worker recall bound. Extended M1's 150 ms recall trigger to every worker count, retained asynchronous exit/resource admission, and required the two-long-background-jobs foreground-arrival test. The trigger is not an image-ready guarantee; borrowing is disabled if App latency gates fail.
