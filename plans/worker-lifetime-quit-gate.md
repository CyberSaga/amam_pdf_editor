# Worker lifetime at exit: one application-level quit gate

Status (2026-11-23 01:30): revision 3 implemented; Opus reviewed revision 1, Astra reviewed revisions 1 and 3. Astra round 8 findings OPEN and not revised (fifth round on one mechanism, owner decision): see plans/cad-m0-h23-review.md "Round 8". Committed as an improvement over HEAD if the whole suite is green. Owner go-ahead 2026-11-23 ("依 worker 生命週期的應用程式層級關閉設計").
Revised design in one line: admission is closed on every quit route; every controller QThread starts through `WorkerRegistry.start_owned(thread, cancel)`; `main.run` keeps draining after `app.exec()` returns. The "allowlist" and `track_thread` of the first design are gone.
Closes the class from plans/cad-m0-h23-review.md, Astra rounds 4-6 (W1-W5): a background worker's lifetime has no single owner
that decides when the process may exit.

Provisional decisions (mine, owner may change):
- Scope: every controller-created QThread. ScanVerifier, search and OCR register; the others are either registered or on an
  allowlist with a one-line reason enforced by a guard test.
- Exit waits without blocking the GUI thread. QThread.terminate() is never called.
- Hard ceiling QUIT_CEILING_MS = 30000. Past it: log the survivors, flush logging, os._exit(0). Reason: a normal exit with a
  live Python thread under PySide6 can deadlock in ExitProcess (memory: test-hang watchdog findings), so a lingering worker
  plus an ordinary exit is the worst outcome. The longest uncancellable step known: one OCR page; the verifier lex checks its
  cancel flag every few thousand tokens and is capped at 8 MiB (about 1 s).

## Design
1. Registry (controller/worker_registry.py). Entries provide `cancel()` (non-blocking) and `alive() -> bool`.
   - `cancel_all()`: cancel every entry once, non-blocking.
   - `alive()`: the entries still running; an entry whose alive() is False is dropped.
   - `track_thread(thread, cancel)`: registers an adapter for a bare QThread; alive() is
     `shiboken6.isValid(thread) and thread.isRunning()`; it unregisters on thread.finished. Used by search and OCR, which drop
     their own references to the thread in cancel() before it has finished.
   - `shutdown_all(timeout_ms)` (blocking) is removed from the teardown path; keep it only if a test or retire path needs it.
   - W2: no blanket `except RuntimeError: done`. Deleted-object detection is `shiboken6.isValid` on the entry's own thread.
2. Quit gate (main.py `finish_owned_shutdown`). Quit only when every owned service has no process AND
   `get_registry().alive()` is empty AND `live_ext_b_subset_threads()` is empty. Otherwise re-poll by
   `QTimer.singleShot(10, ...)`. `shutdown_owned_processes` cancels once (registry `cancel_all()`, services
   `shutdown()`) and starts the poll; no blocking wait on the GUI thread. Past QUIT_CEILING_MS from the first quit
   request: log survivors, flush handlers, `os._exit(0)`.
   - `app.quit()` at main.py:503 is the only quit call in main.py, view/ and controller/ (grep 2026-11-23). The aboutToQuit
     handler stays as a last check that logs anything still alive; the second-pass and `draining` logic goes.
3. W3: PDFView emits a new `closed` signal from closeEvent only when the event ends accepted (after handle_app_close).
   main.py connects release_context to `closed` and `destroyed`; release_context is idempotent. No WA_DeleteOnClose
   (the tab handoff holds view references).
4. W4: search_coordinator and ocr_coordinator call `get_registry().track_thread(thread, worker.request_cancel)` when they
   start a thread.

## Tests (red first, against the current code)
- Process-level outcome test (new file test_scripts/test_quit_gate_process.py): a subprocess runs the real main.run teardown
  with one registered worker held on an event past the old 5 s deadline (drain timeout patched small). Request quit; assert the
  process is still alive after the old deadline; release the worker; assert exit code 0 and a marker written by the worker's
  run() after release. Second case: worker never released, ceiling patched to about 2 s; assert the process exits by
  os._exit within ceiling + slack and logs the survivor.
- Enumerating guard: every `QThread(`, `moveToThread` and QThread subclass site under controller/ belongs to a class that
  registers (track_thread / register) or is on an explicit allowlist with a reason. Seed allowlist from Astra round 6:
  page render, thumbnail (joined or close deferred by handle_app_close), print, optimize/text commit, pdf_controller:2446.
  ext_b lives in view/ and is covered by the gate condition, not the registry.
- W3: closing a secondary window (hide, not destroy) runs release_context exactly once; an ignored close does not.
- W2: a worker whose cancel raises a non-deletion RuntimeError stays alive in the registry.
- Existing test_scan_verifier_shutdown.py adapted: no quit() stub, no hand-invoked second pass.

## Done
ruff, touched tests, whole suite once at the end, PITFALLS entry + index, ARCHITECTURE line (registry + quit gate), TODOS,
plan-code-reviewer (Opus), then one Astra review group.

## Running log
- 2026-11-23: plan written.
- 2026-11-23: implemented. Red first: gate tests 8 failed, process tests 2 failed (child crashed 0xC0000409 on exit with a live QThread). Registry cancel_all/alive/track_thread, ScanVerifier cancel()/alive(), search/OCR track_thread, PDFView.closed + idempotent release_context, main quit gate (poll, QUIT_CEILING_MS read from controller.worker_registry at call time, os._exit past it, aboutToQuit only logs). shutdown_all removed. test_scan_verifier_shutdown.py and test_tab_drag_back.py (closed secondary no longer stays registered) adapted. Process cases: held worker exits 0 about 0.05 s after release; never-released worker cut at 1.98 s with a 2 s ceiling.
- 2026-11-23 (round 7 findings and the revision): Astra: direct app.quit() bypassed the gate (aboutToQuit only logged, exec returned with a worker running; Ext-B blocked in its own aboutToQuit), a start queued behind the accepted close and a worker admitted during polling slipped past the one-time cancel, a promoted secondary released twice (A,B,C), run(start_event_loop=False) had no completion contract, the guard checked files not sites, the process tests entered through the private shutdown function. Opus: render/thumbnail threads start AFTER the accepted close via the visible-render QTimer chain while the gate polls (probe: exec returned with a thread running, then 0xC0000409); the allowlist reasons were false for text_commit. Revision (one change): `WorkerRegistry.close_admission/open_admission/start_owned(thread, cancel) -> bool` (register + start atomically; refusal leaves the thread unstarted and the caller undoes its state: search, OCR, page render, thumbnail, plan preview, print, optimize and ScanVerifier each do); `main._begin_shutdown` (admission, Ext-B refusal, cancel, services) on every route including aboutToQuit; every 10 ms poll cancels again; `exec_and_drain` keeps pumping after app.exec() returns until registry, Ext-B threads and services are idle or the ceiling (from the first request) passes; `startup_ctx["quit_gate"]` (request/done); one idempotent `_release_window` per controller for accepted close, destroyed and promotion (retire_background also cancels search and OCR); Ext-B `refuse_new_ext_b_threads` replaces its blocking aboutToQuit wait; `shutdown_background` and `ObjectProbeCoordinator.shutdown` deleted. Found while testing: a `finished` connection that unregisters (as the first design's `track_thread` did) runs ON the worker thread and drops the last wrapper reference there ("Destroyed while thread is still running", native abort), so finished entries are swept from the GUI thread in `start_owned`/`alive()` instead. Tests: test_worker_registry_gate.py (AST guard with injected-source proofs, admission, F release A,B,C, Ext-B, quit-gate handle) and test_quit_gate_process.py (parametrised invariant: last close with a render in flight, direct quit, promoted close, queued start; ceiling case with lower and upper bound and exec_returned absent). TODOS: harness adoption of `startup_ctx["quit_gate"]` is OWED (tests that drive run(start_event_loop=False) should request() and pump until done()).
- 2026-11-23 (Astra probe fixes, four items): (1) `_ThreadEntry.alive()` is True until `start()` returned AND `wait(0)` is True (shiboken-invalid counts as finished): a blocking DirectConnection `finished` handler no longer reads idle. (2) entries carry `started`, False from admission (under the lock) until `start()` returns; such an entry is never swept and stays alive after `close_admission`. (3) `retire_worker_with` returns its retirement; search, OCR, page render, optimize and print call `retirement.release()` on a refused start (probe: 5 leaked `_retirements`, now 0). (4) the AST guard is per site: a QThread construction must be a direct `start_owned` argument or assigned to a name passed to it in the same function scope, nested functions are separate scopes. Red first: guard string cases returned `[]`; blocking-handler and not-yet-started tests failed with the old alive(); retirement test failed with `5 == 0`. Tests in test_worker_registry_gate.py; the old W2 test now sets `entry.started`.
