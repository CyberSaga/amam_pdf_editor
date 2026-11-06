# Heavy-file speed (docs/to_Update.md lines 2-3)

## Replacement execution plan (2026-11-06)
- Use [App performance v2](app-performance-v2.md) as the evidence-gated draft and acceptance contract. It supersedes the execution constraints below; the older design and running log remain historical evidence.
- The next integration sequence includes a budget-admitted two-worker process profile and bounded hot-page DisplayList reuse (one list per worker, two App-wide), compared against one-worker/no-list controls. Three/four workers remain diagnostic options; direct clip is deferred on pixel counterexamples. App release/default admission, absolute budgets and the owner's total +300 MiB allowance remain gates, not achieved results.
- This plan revision does not implement those changes or restart the owner-paused full suite.

## Current state and next step
- 2026-11-05: **the owner approved step 1 on 2026-11-05 and explicitly requested Step 2 app integration/measurement on 2026-11-06** (out-of-process page raster).
  - An adversarial review (21 items) was checked against the code and folded into the steps.
  - Points the code contradicts are listed at the end.
- **Product code:** Step 1 foundation and optional Step 2 app-wide page client implemented. Queue, cancellation, stale-result checks, fallback, quarantine, save holds and tab/window/application cleanup are wired. Independent source review: ship, no remaining concrete defect identified. Full performance acceptance remains open.
- **Step 0:** committed as `60b66eb`; final heavy-file remeasurement used the 300 s settle cap, three runs, no censored settles. This does not establish every Step 0 performance gate.
- **Step 1 checks:** 270 focused tests passed (protocol 11, child 12, raster 6, config 1, page coordinator 15, thumbnail coordinator 22, benchmark settle 5, suite-runner unit 198). Real app supervisor exit 0; mypy, four import contracts, ruff and device scan passed. Full suite and full-scenario 3-by-3 benchmark gates remain open; targeted Step 2 App sequence is measured below.
- **0a DONE (2026-11-05):** `_background_busy` also treats a coordinator's live `_threads` as busy; idle must hold `SETTLE_HOLD_S = 0.25`. Settle tests red 2 → 5 pass.
- **0b DONE, 0c measured (2026-11-05):** GIL hypothesis confirmed (freeze/raster 0.90-0.95); worst freezes hvac 27 s, heavy 104 s input delay. See running log. Heavy file re-measured with the 300 s settle cap.
- **NEXT:** Step 2 wiring/review/targeted measurement complete; performance acceptance failed on heavy open/zoom and background stalls. Thumbnail/first-paint migration belongs to Steps 3/4, not this implementation. Retain open full-suite/full benchmark gates and thread default. Commit only when the owner asks.
- **Root cause status.** "PyMuPDF holds the GIL during raster" was measured once, standalone:
  - `plans/archive/2026-07-17-m3-manual-round2-defects.md:74-76`: a 10 ms tick stalled for a median of 197 ms and a max of 4.5 s while a `threading.Thread` rastered 5 dense pages (TODOS.md:1675).
  - Step 0's `gil_probe` repeats this inside the harness, with the app's own `_PageRenderWorker` on a QThread, so the gate can be re-run in-tree.
  - Contingency, not expected: if most of the stall is synchronous GUI-thread work (`sync_render_ms`, `snapshot_capture_ms`), do step 4 before step 2 and bring the plan back to the owner.
- **Design in brief:**
  - one app-wide child process (`src/render_worker/worker_main.py`), created in `main.py` and injected into every `PDFController`;
  - the queue lives in the parent, with one job in flight and two lanes (page before thumbnail);
  - pixels come back as raw RGB in binary frames on stdout;
  - a clean document is loaded by path (read, then the handle is closed);
  - a dirty document is streamed once per (session, revision) from a lazy snapshot provider;
  - the QThread path stays the fallback for every failure.
- **Flag:** `PDF_EDITOR_RENDER_WORKER=thread|process`. The default stays `thread` until step 5. The test suite is always pinned to `thread`.
- **Decision rule:** a step passes on GUI stall (heartbeat gap and input latency), not on median time to content. A separate process cannot make a raster faster; it only stops the raster from freezing the GUI.
- **Unchanged until the step named:**
  - watermarked sessions stay synchronous for the whole plan (`test_page_render_coordinator.py:264`);
  - the synchronous immediate low paint stays until step 4;
  - `jump_to_result`, single-page mode, search, OCR and plan preview stay out of scope.
- Open questions are at the end. None blocks step 0 or step 1.

## Measurements (median of 3, ms; 2026-11-05, this machine, tree with the to_Update sweep)
| scenario | office-report 23p | hvac-dwg 50p | 開起來很卡 90p |
|---|---:|---:|---:|
| startup_wall | — | 968 | 841 |
| open_first_paint | 449 | 808 | 1051 |
| zoom_settle | 27 | 69 | 54 |
| f5_enter | 97 | 157 | 9142 |
| f5_exit | 57 | 9805 | 82 |
| scroll_step_content | 32 | 437 (p90 5263) | 1583 (p90 2892) |
| scroll_sweep_total | 1234 | 69620 | 71144 |
| tab_switch_high | 24 | 3820 (p90 13940) | 42 |
| bg_after_open | 363 | ≥12073 (censored) | ≥13082 (censored) |
| bg_after_zoom | 43 | 6066 | ≥10127 (censored) |

- **Censored values.** The old settle stopped at 10 s, so values marked ≥ are lower bounds. Each overshoot past 10 s is one `processEvents()` call that ran past the deadline, which is itself a GUI stall of 2-3 s.
- **Scroll and tab rows** ran while thumbnail QThreads were still active. Step 0 replaces this whole table.
- **Thumbnail raster alone** (fitz only, one full pass): office 5.2 ms/page, hvac 282 ms/page, heavy 416 ms/page.
  - 380 px vs 270 px: render time x1.03-1.17, QImage memory x1.98 (heavy file: 37 MB → 74 MB).

## Goal
Keep the UI responsive (heartbeat gap and input latency) while heavy CAD-style PDFs render pages and thumbnails. Time to content must not regress, and nothing may become worse than today when the worker fails.

## Modules
- **New, Qt-free:**
  - `model/page_raster.py`: `RasterSamples`, `rasterize_page`, `rasterize_thumbnail`. It imports only `fitz`, `utils.render_limits` and `model.color_profile` (which imports only `enum`, `typing` and `fitz`).
- **New, stdlib only:**
  - `src/render_worker/__init__.py` (follows `src/printing/__init__.py`);
  - `protocol.py`;
  - `outcomes.py` (`RenderTransportLost`, `RenderTimedOut`, `RenderOversize`, `RenderUnavailable`);
  - `config.py`.
- **New child entry:** `src/render_worker/worker_main.py`.
  - It imports `fitz`, `model.page_raster` and the stdlib, never `pdf_model`.
  - `src/` lies outside the import-linter roots (`pyproject.toml:76`) and outside the `threading.Thread` grep (`.github/workflows/ci.yml:160-167`).
- **New parent client:** `src/render_worker/process_client.py` defines `RenderProcessClient(QObject)`.
  - Its seams copy `src/printing/subprocess_runner.py`: `process_factory`, `python_executable`, `monotonic`.
  - The controller may import from `src.render_worker`, as it already imports `src.printing`.
- **Changed:**
  - `main.py`;
  - `controller/page_render_coordinator.py`, `controller/thumbnail_coordinator.py`, `controller/pdf_controller.py`;
  - `utils/helpers.py` (`qimage_from_samples(samples, width, height, stride, alpha)`, primitives only, because utils may not import model);
  - `test_scripts/conftest.py`, `scripts/run_suite.py`, `scripts/benchmark_ui_perf.py`.

## Architecture (load-bearing rules only)
- **One app-wide client and one child** (decision D1).
  - `main.run` creates the client after the single-instance hand-off (`main.py:292-298`) and before `view.show()` (`:300`), then schedules `client.start` with `QTimer.singleShot(0)`.
  - It stores the client in `startup_ctx["render_client"]` and passes `render_client=` to both `PDFController(...)` calls (`:141`, `:238`).
  - It connects `app.aboutToQuit` to `client.shutdown`.
  - When the mode is `thread`, it creates no client.
  - Each controller calls `client.register_owner()`. `release_context` (`:158-161`) and promotion (`:268-270`) call `controller.release_render_owner()`.
- **Scheduler (in the parent):**
  - `submit(RenderJob)`, `cancel(job_id)`, and the signal `job_done(job_id, JobOutcome)`, connected to bound slots only (GATE15-3);
  - `RenderJob(job_id, owner, lane: "page"|"thumb", doc: DocSource, page_index, scale, color_profile, kind)`;
  - at most one render in flight; the next job sent is the oldest page-lane job, otherwise the oldest thumb-lane job;
  - thumbnails are submitted one page at a time, with job id `f"{batch_token}:{page}"`, so a thumbnail can wait behind at most one raster.
- **Document slot.** The child holds one document. The client records `loaded_key` itself (review item 13); it never infers it from the parent's snapshot cache, which is dropped without a revision bump at `pdf_controller.py:2648`, `:4728` and `ocr_coordinator.py:278`.
  - `DocSource(doc_key, file: FileRef | None, snapshot_provider)`, where `doc_key = f"{session_id}@{render_revision}"`. Session ids are uuid4 (`model/pdf_model.py:1808`, `:1878`), so keys are unique across windows.
  - If `loaded_key` differs from the job's key, the client sends `drop_doc` and then a load.
  - The provider is called on the GUI thread only when a load is needed. It returns None when the session or revision is no longer current; the job then ends as `stale`.
- **Protocol:**
  - Frame: `struct ">2sBIQ"` (magic `b"RW"`, version 1, header length, body length), then the UTF-8 JSON header, then the body.
  - The header is at most 64 KiB in both directions.
  - Parent → child: `load_path{doc_key, path, size, mtime_ns}`, whose body is the UTF-8 password (empty if none), so a password never appears in a header, argv or the environment; `load_bytes{doc_key}`, whose body is the snapshot; `drop_doc{doc_key}`; `render{job, doc_key, page, scale, profile, kind}`; `quit`.
  - Child → parent: `ready{pid, fitz_version}`; `doc_ready{doc_key, page_count}`; `doc_failed{doc_key, reason}`, with reason in {changed, auth, open, too_large}; `image{job, w, h, stride, n, alpha}`, whose body is the samples; `error{job, reason, exc_type}`.
- **Size limits** (item 11, a separate limit per direction):
  - `MAX_LOAD_BYTES = 512 MiB`. The parent checks `stat.st_size` or `len(snapshot)` before it sends; a document over the limit uses the thread backend for that session.
  - `MAX_IMAGE_BYTES = 160 MiB` (40 MP x 4 bytes). The child refuses before rastering when `ceil(w*s) * ceil(h*s) * 3` exceeds it, because the 0.1 floor in `safe_render_scale` (`utils/render_limits.py:28-38`) can exceed 40 MP. The parent then runs that one job on the thread path, as happens today.
- **Parent decode** (item 11):
  - the client reads chunks of at most 4 MiB into one preallocated `bytearray(body_len)`;
  - it builds one `QImage(...).copy()` and drops the buffer;
  - that is two frame-sized copies, the same as in-process (fitz samples plus a QImage copy); the draft's "same as in-process" was wrong only about the decode path.
- **Child:**
  - At start it runs `out = os.fdopen(os.dup(1), "wb")`, `os.dup2(2, 1)`, `sys.stdout = sys.stderr`, and calls `fitz.TOOLS.set_small_glyph_heights(True)` (the app sets no other process-global raster switch; checked by grep).
  - It runs a single-threaded loop: read a frame, handle it, write, `flush()` (item 18).
  - It exits 0 on stdin EOF.
  - `load_path`: stat-check, read the whole file, close the handle, `fitz.open(stream=…)`, authenticate with the body password.
  - It calls `store_shrink(100)` whenever it replaces the document.
- **Child environment:** a copy of `os.environ`, the project root prepended to `PYTHONPATH`, `PYTHONIOENCODING=utf-8` and `PYTHONUTF8=1` (PITFALLS 1549-1550). It never sets a password variable (unlike `subprocess_runner._build_helper_env:96-97`).
- **Failure handling:**
  - `FailedToStart` emits no `finished` (PITFALLS 1648), so the client cleans up by hand and uses `thread` for the rest of the run.
  - An unexpected exit with a job in flight gives `transport_lost`.
  - A job running longer than 120 s is killed deliberately and gives `timeout`.
  - Three unexpected exits within 120 s disable the backend for the run. Timeouts, save-hold kills and preemption kills do not count.
  - On every respawn the client creates a new `FrameDecoder` and disconnects the old QProcess (item 17).
  - Every terminal path emits exactly one `job_done` (item 16): image, error, transport_lost, timeout, oversize, cancelled (a queued job is reported on the next turn), stale, unavailable (backend not ready or disabled while queued; the coordinator reruns the job on the thread path) and owner_released.
- **Stderr:** the client always reads stderr and logs at most 64 KiB per minute (item 18). It never formats headers into logs or exceptions; `ProtocolError` carries only the message type and the lengths. `FileRef.password` is declared `field(repr=False)` and dropped once written (item 12).
- **Quarantine (the review's "poison"; item 3):**
  - The controller holds a set of `(session_id, page_xref)`, using `fitz.Document.page_xref` so it needs no page load; check this in the red test.
  - Only `transport_lost` adds a page; timeouts and deliberate kills never do.
  - Edits do not clear it, and it survives a disabled backend.
  - One helper, `_raster_quarantined(sid, page_idx)`, guards every GUI-thread raster:
    - `_render_page_into_scene` (`:1177-1216`, which covers the `:1399` immediate paint and the `:1448` fall-through);
    - `_dispatch_page_render_request` and the `_process_visible_render_batch` candidates;
    - `jump_to_result` (`:4194`), `change_scale` single-page (`:4384`), `show_page` (`:4637`);
    - `_render_live_thumbnail` (`:4474-4479`), which returns a grey placeholder;
    - the thumbnail file worker, through `skip_pages` passed in the request.
  - A quarantined page keeps its placeholder, with one warning toast per page.
  - A tab dragged to another window gets a new uuid (`model/pdf_model.py:1878`), so its quarantine does not follow it. This is accepted.
  - `get_page_snapshot` (`:2813`, `:4874`: print preview and `snapshot_page`) is out of scope.
- **Save interplay (item 6):**
  - Today `_background_file_readers_released` (`:2258-2285`) joins only the thumbnail coordinator, with `thread.wait`.
  - In process mode it also runs `client.path_loads_held(SAVE_READER_JOIN_TIMEOUT_MS)` around the `yield`:
    - a latch stops any new `load_path` (other jobs may still go);
    - an unacknowledged `load_path` is waited for with `waitForReadyRead`, with frames decoded but queued, not delivered;
    - if the wait times out, the client kills the child deliberately (no quarantine);
    - when the latch is released, the queued frames are delivered with `singleShot(0)`.
  - The latch is needed because `file_share_lock.suspended` drops the deny-write handle during the write (`utils/file_share_lock.py:333-360`). Python's `open('rb')` does not share delete, so a child opening the file at that moment makes `os.replace` fail (R7-2).
  - Because the client is app-wide, this one latch also covers a second window reading the same file.
- **App and window close (item 10):**
  - `handle_app_close` (`:5356-5366`) runs before the print and optimize ignores and before the save prompt's Cancel (`:5370-5452`). It therefore never quits the child; it only cancels its own jobs, and `wait_for_done` returns True for process jobs.
  - The child quits only on `aboutToQuit`: send `quit`, call `closeWriteChannel()`, `waitForFinished(500)`, then `kill()`.

## Steps (each ships alone behind the flag; `thread` remains a working fallback in every step)

### Step 0: settle, stall probe, re-baseline (harness only, no product change)
- **0a settle (finish the work already in the tree):**
  - `_background_busy` must also return True while either coordinator's `_threads` is non-empty. `ThumbnailCoordinator.cancel()` clears `_active` (`controller/thumbnail_coordinator.py:153-160`) while its QThread is still inside `get_pixmap`, and every visible render cancels thumbnails (`pdf_controller.py:1346-1348`).
  - Idle must hold for `SETTLE_HOLD_S = 0.25`, because batches chain through `singleShot(0)` (`:752-759`, `:1405-1408`).
  - Record `thumbs_done/pages` for each settle.
- **0b probe:**
  - A `HeartbeatProbe` uses a 5 ms `Qt.PreciseTimer` and records lateness.
  - An input probe posts a custom `QEvent` every 20 ms and records the time from post to handling.
  - `_pump` and `_wait` record the duration of each `processEvents()`.
  - Per scenario: `gap_max_ms`, `gap_p95_ms`, `input_latency_p95_ms`, `input_latency_max_ms`, `pump_max_ms`.
  - Counters:
    - `sync_render_calls/ms` (wrap `model.get_page_pixmap`);
    - `live_thumb_calls/ms` (wrap `model.get_thumbnail`);
    - `snapshot_capture_calls/ms` (wrap `controller.capture_worker_snapshot_bytes`);
    - `render_dispatched/consumed`;
    - parent `peak_rss_mb` through ctypes `K32GetProcessMemoryInfo`, with `GetCurrentProcess.restype = wintypes.HANDLE` and full argtypes (PITFALLS 2305).
  - New scenario `gil_probe`, run after the open settle: a `_PageRenderWorker` on a QThread renders page 0 at 2.0 while the probes run. Record `gil_probe_raster_ms`.
  - `_summary` adds p95.
- **Tests (red first):**
  - Add to `test_benchmark_ui_perf_settle.py` (the existing three stay):
    - `test_settle_waits_for_a_cancelled_thumbnail_thread`: `has_active_job` is False but `_threads` is non-empty for 30 polls; all polls are consumed and the run is not censored;
    - `test_settle_requires_idle_to_hold`: busy, then idle for one poll, then busy for 20 polls; the settle does not return at the first idle poll.
  - New `test_scripts/test_benchmark_stall_probe.py` (Qt):
    - `test_gap_probe_records_blocking_handler`: a 200 ms sleeping slot gives `gap_max_ms` ≥ 180; an idle 500 ms gives `gap_p95_ms` < 20;
    - `test_input_latency_probe_records_blocked_turn`: a 150 ms block gives `input_latency_max_ms` ≥ 130;
    - `test_pump_duration_recorded_per_process_events`;
    - `test_sync_render_counter_wraps_get_page_pixmap`: two calls give count 2 and ms > 0.
- **0c re-baseline:**
  - Command: `.venv\Scripts\python.exe scripts/benchmark_ui_perf.py --runs 3 --child-timeout 1800 --files test_files/office-report-23p.pdf test_files/hvac-dwg.pdf "test_files/疑似結構不佳的PDF(開起來很卡).pdf"`.
  - The default `--child-timeout` of 300 s (`:529`) is shorter than the 120 s cap times the run's 13 settle calls.
  - Replace the table with medians and gap metrics.
- **Accept when:**
  - no settle is censored on any file;
  - `gil_probe` `gap_max_ms` agrees within 20% across the three runs on hvac and heavy;
  - the hypothesis counts as confirmed if `gap_max_ms` ≥ 0.8 × `gil_probe_raster_ms`; otherwise follow the contingency in the top block.
- **Commit** the harness and tests (`ruff check .` clean, both test files green).

### Step 1: shared raster, protocol, child, test-infrastructure pins (no wiring; the flag changes nothing yet)
- **Changes:**
  - `model/page_raster.py`:
    - `RasterSamples(width, height, stride, n, alpha, samples)`, frozen;
    - `rasterize_page(doc, page_index, scale, color_profile)`: clamps with `safe_render_scale`, uses `annots=True` and `safe_to_fitz_colorspace`, and converts GRAY/CMYK to RGB exactly as `utils/helpers.py:29-30` does;
    - `rasterize_thumbnail(doc, page_index, color_profile)`, using `thumbnail_render_scale`.
  - `_PageRenderWorker.run` (`page_render_coordinator.py:64-79`) and `_ThumbnailWorker.run` (`thumbnail_coordinator.py:70-73`) call these functions and then `qimage_from_samples`.
  - `src/render_worker/{__init__,protocol,outcomes,config,worker_main}.py`, as in Architecture.
    - `FrameDecoder(max_header, max_body).feed(chunk) -> list[Frame]` writes the body into one preallocated buffer.
    - `encode_prefix(header, body_len)` lets large bodies be written without concatenation.
    - `render_worker_mode()`: unset gives `thread` (until step 5); an invalid value gives `thread` and one warning; `sys.frozen` gives `thread`.
  - `test_scripts/conftest.py`, next to `:14-17`: `os.environ["PDF_EDITOR_RENDER_WORKER"] = "thread"`. Assign it rather than `setdefault`, like `PDF_EDITOR_PRINT_LOG`, so a developer's shell value cannot leak into tests. Real-child tests opt in with `monkeypatch.setenv` (item 1).
  - `scripts/run_suite.py:61`: `_FORCE_QT = {"test_scripts/test_render_worker_child.py"}`. That file then runs in its own interpreter under the per-file stall kill instead of the shared pure lane (items 1 and 19). Protocol and raster tests stay pure.
  - `scripts/benchmark_ui_perf.py`: add `--render-worker {thread,process}`, default `thread`, set through a factored `_child_env(args)`. `_spawn` copies `os.environ`, so without this the shell's value leaks into the A/B. Record the mode in the JSON.
- **Tests (red first):**
  - Pure, `test_scripts/test_page_raster.py`:
    - `test_rasterize_page_matches_direct_get_pixmap_for_rgb_gray_cmyk`: samples and (w, h, stride, n) are byte-equal to a direct `page.get_pixmap` plus the RGB conversion, on a page with an annotation;
    - `test_large_page_preserves_existing_scale_clamp_without_allocating_40mp`: a real 20000 pt square page at scale 2 delegates with the existing `safe_render_scale`; integer raster rounding can add a boundary row/column. Preserve this thread behavior rather than tightening the global limit in Step 1. Child transport separately enforces its byte budget before rendering.
    - `test_rasterize_thumbnail_width_follows_thumbnail_render_scale`;
    - `test_page_raster_imports_neither_qt_nor_pdf_model`: in a fresh interpreter, neither `PySide6` nor `model.pdf_model` is in `sys.modules`.
  - `test_page_render_coordinator.py`:
    - `test_page_render_worker_calls_shared_rasterizer`: the spy is called once with (page, rendered_scale·dpr, profile); `:76` still passes.
  - `test_thumbnail_coordinator.py`:
    - `test_thumbnail_file_worker_calls_shared_rasterizer`: one call per page.
  - Pure, `test_scripts/test_render_worker_protocol.py`:
    - `test_frame_roundtrip_header_and_body`;
    - `test_frame_decoder_split_and_coalesced_chunks`: the same frames whether fed byte by byte or all at once;
    - `test_frame_decoder_rejects_bad_magic_version_and_oversize_per_direction`;
    - `test_frame_decoder_body_is_one_preallocated_buffer`;
    - `test_protocol_error_text_never_contains_header_content`: `"s3cret"` is absent;
    - `test_image_header_requires_n_and_alpha`.
  - Pure, `test_scripts/test_render_worker_config.py`:
    - `test_mode_unset_is_thread`, `test_mode_process`, `test_mode_invalid_warns_once_and_is_thread`, `test_mode_frozen_is_thread`;
    - `test_conftest_pins_render_worker_thread`.
  - `test_scripts/test_render_worker_child.py` (`_FORCE_QT`; `subprocess.Popen([sys.executable, "-m", "src.render_worker.worker_main"])`; every read goes through a helper with a hard 10 s timeout; a fixture finalizer kills the child):
    - `test_child_ready_reports_pid_and_parent_fitz_version`;
    - `test_child_render_is_byte_equal_to_inprocess_rasterize_page` (RGB, GRAY, CMYK);
    - `test_child_stdout_carries_only_frames_under_mupdf_warnings`: on a broken fixture the decoder raises nothing and stderr is non-empty;
    - `test_child_exits_on_stdin_eof_within_2s`;
    - `test_child_path_load_releases_the_file_handle`: `os.replace` over the path succeeds after `doc_ready`;
    - `test_child_path_load_rejects_changed_stat`: `doc_failed` with reason `changed`;
    - `test_child_password_only_in_body`: the env has no password; a wrong password gives `doc_failed auth`; the password is absent from stderr and from every header;
    - `test_child_refuses_oversize_before_raster`: `error oversize` within 1 s.
  - `test_run_suite.py`: `test_render_worker_child_tests_get_their_own_qt_job`: a pure source under that path classifies as `qt`.
  - `test_benchmark_ui_perf_settle.py`: `test_render_worker_flag_sets_child_env`: the default is `thread`, and `--render-worker process` gives `process`.
- **Accept when:**
  - every new test was seen red, then green;
  - `ruff check .` is clean, `mypy model/ utils/` is clean, and the four lint-imports contracts pass;
  - `scripts/run_suite.py` exits 0;
  - the harness with `--render-worker thread`, 3 runs on 3 files, keeps medians and `gap_*` within max(15%, spread) of step 0.
- **Docs:** ARCHITECTURE entries for `model/page_raster.py` and `src/render_worker/`.

### Step 2: page render through the shared client (`process`)
- **Changes:**
  - `process_client.py`: everything in Architecture except thumbnails.
  - `main.py`: create, inject, schedule the deferred spawn, `aboutToQuit`, owner release.
  - `PageRenderCoordinator`:
    - `__init__(..., backend=None)`;
    - `PageRenderRequest(identity, snapshot_bytes: bytes | None = None, document: DocSource | None = None)`;
    - `request(..., snapshot_bytes=None, document=None)` stays backward compatible;
    - `_start_worker` routes the job to the client when the client is ready and `document` is set. Otherwise it takes today's QThread path (`_threads`, `_PageRenderWorker`, GATE15-3 wiring unchanged). When `snapshot_bytes` is None it first calls `document.snapshot_provider()` once on the GUI thread (item 5);
    - a bound slot `_on_job_done` leads to `_job_finished(token)`, which mirrors `_thread_finished` so `_pending` still chains (item 16);
    - `wait_for_done` only cancels process jobs.
  - `PDFController`:
    - `__init__(model, view, *, render_client=None)` (`:283`);
    - `_dispatch_page_render_request` (`:1247-1296`): with a client it builds a `DocSource` with no eager capture; a clean session gets a `FileRef` with the same test as `_resolve_thumbnail_file_source` (`:4451-4472`); quarantine and skip checks;
    - `_process_visible_render_batch` (`:1410-1458`): leaves quarantined pages and skipped identities out of the candidates;
    - `_on_page_render_failed` (`:1327-1344`): on `RenderTransportLost` it quarantines the page; on `RenderTimedOut` it adds `(sid, revision, page, quality, rendered_scale)` to the skip set. Both then keep the batch pending and reschedule it with `singleShot(0)` (item 4). Any other failure keeps today's stop, which `:235` pins;
    - the quarantine chokepoints;
    - `_background_file_readers_released` (save hold);
    - `release_render_owner()`.
  - Harness:
    - `frame_gui_ms`, `doc_loads`, `ipc_bytes`, child `peak_rss_mb`;
    - kill `startup["render_client"]` before `os._exit(0)` (`:405`).
- **Tests** (fake QProcess, as in `test_print_subprocess_runner.py`; `test_scripts/test_render_process_client.py` plus the controller tests):
  - `test_scheduler_one_in_flight_page_lane_before_thumb_lane`: submitting thumb, thumb, page sends thumb1, then page, then thumb2;
  - `test_cancel_queued_job_reports_cancelled_next_turn`;
  - `test_every_terminal_path_clears_active_and_chains_pending`, parametrised over the nine outcomes: afterwards `has_active_job` is False or the pending job has started;
  - `test_process_backend_one_active_latest_pending` and `test_process_result_rejected_on_any_stale_identity` (the parametrised `:99` and `:194`);
  - `test_dirty_doc_streams_once_per_key_lazily`: two requests give one `load_bytes` and one provider call; a bump gives a second; `_invalidate_worker_snapshot_cache()` without a bump gives no re-stream;
  - `test_clean_session_loads_by_path_without_snapshot_capture`: `capture_worker_snapshot_bytes` is never called;
  - `test_doc_over_load_limit_uses_thread_backend`;
  - `test_requests_use_thread_backend_until_ready`;
  - `test_failed_to_start_falls_back_for_the_run`;
  - `test_backend_loss_before_send_runs_thread_path_with_one_provider_capture`;
  - `test_transport_loss_quarantines_page_and_resumes_batch`: `get_page_pixmap` is never called for that page through `:1399`, `:1448`, `:4194`, `:4384` or `:4637`; other pages render; `:235` is unchanged;
  - `test_quarantine_survives_revision_bump_and_backend_disable`;
  - `test_timeout_and_deliberate_kill_do_not_quarantine_or_count_as_crash`;
  - `test_three_crashes_in_120s_disable_backend`;
  - `test_every_gui_raster_call_checks_quarantine`: a source-grep guard; every function in `controller/pdf_controller.py` that calls `self.model.get_page_pixmap(` or `self.model.get_thumbnail(` also calls `_raster_quarantined(`;
  - `test_save_holds_path_loads_and_defers_delivery`: the order is `[hold, ack, save, release]`; no `load_path` is written between hold and release; a frame decoded during the hold is delivered after release;
  - `test_save_hold_timeout_kills_child_without_quarantine`;
  - `test_shared_client_two_controllers_one_child`: one spawn; `release_owner` drops only that owner's jobs and document;
  - `test_window_close_cancel_keeps_child_alive`: Cancel at the prompt, then the next render still uses the process backend;
  - `test_about_to_quit_quits_then_kills_child`;
  - `test_main_run_creates_no_client_when_thread_pinned`;
  - `test_respawn_resets_decoder_and_ignores_old_process`;
  - `test_stderr_always_drained_and_log_bounded`: 10 MB of stderr is fully read and at most 64 KiB is logged;
  - `test_password_never_in_header_env_repr_or_logs`;
  - `test_worker_env_pins_pythonioencoding_and_utf8`;
  - `test_frame_decode_one_buffer_one_qimage_copy`;
  - leak guard `test_process_backend_leaves_no_child_after_teardown`;
  - one real-QProcess test in its own file, `test_render_worker_live.py`: `test_live_process_keeps_event_loop_responsive_on_dense_page` (a generated page with about 200k segments at 4x; heartbeat lateness < 100 ms).
- **Accept** on hvac and heavy with `--render-worker process`, against the step 0 baseline. Measurements are taken after a `pre_scroll` settle that was not censored, so step 2 does not depend on step 3 (item 7):
  - scroll sweep `gap_p95_ms` < 50 and `gap_max_ms` < 150;
  - `input_latency_p95_ms` < 50;
  - `scroll_step_content` median ≤ baseline + 15%;
  - `tab_switch_high` ≤ baseline + max(15%, spread), with `doc_loads` ≤ 2 per round trip (item 14);
  - `startup_wall`, `open_high` and `bg_after_open` wall time ≤ baseline + max(15%, spread) (item 15: the spawn now happens inside `startup_wall`);
  - office within the spread everywhere;
  - `frame_gui_ms` p95 < 8;
  - parent plus child peak RSS ≤ step-0 parent peak + 150 MB on heavy.
- **Docs:** an ARCHITECTURE render-worker section; PITFALLS entries for stdout fd hygiene, the save hold and quarantine.

### Step 3: thumbnails through the client (clean and dirty)
- **Changes:**
  - `_resolve_thumbnail_file_source` returns `ProcessThumbnailSource(DocSource)` when the client is ready and `get_watermarks()` (`:5008`) is empty. Watermarked sessions keep today's file or live path, because overlays are applied at render time (`model/tools/manager.py:258-283`, through `get_thumbnail` → `get_page_pixmap`, `model/pdf_model.py:3102-3106`) and are not in `tobytes()` (item 9).
  - `ThumbnailCoordinator`: a third strategy that submits one page at a time and cancels the current job.
  - On `transport_lost` it quarantines that page and continues with the next page through the client, instead of `_worker_failed`'s whole-range live restart (`:222-228`).
  - `wait_for_done` is True for process jobs.
  - `_ThumbnailWorker` takes `skip_pages`.
  - New harness scenario `bg_after_edit`: one text edit, then the sweep.
- **Tests:**
  - `test_dirty_unwatermarked_thumbnails_never_raster_on_gui_thread`: neither `model.get_thumbnail` nor `_render_live_thumbnail` is called;
  - `test_watermarked_session_thumbnails_keep_overlay_path`;
  - `test_clean_thumbnail_source_never_captures_snapshot` (`:196` kept);
  - `test_visible_job_preempts_thumbnail_between_pages`;
  - `test_thumbnail_cancel_stops_between_pages`;
  - `test_thumbnail_transport_loss_skips_page_not_whole_range_live`;
  - `test_thumbnail_file_worker_skips_quarantined_pages`;
  - parametrise the real R7-2 tests `:354` and `:365` and the order tests `:395-466` over both backends (item 21).
- **Accept when:**
  - `bg_after_open`, `bg_after_zoom` and `bg_after_edit` have `gap_p95_ms` < 50 and `gap_max_ms` < 150;
  - no unwatermarked GUI-thread thumbnail raster occurs;
  - `visible_wait_behind_thumb_ms` p90 < 200;
  - nothing is censored;
  - RSS stays within the step 2 budget.

### Step 4: adaptive async first paint, rescale while waiting
- **Changes:**
  - Keep a per-session moving average of low-render ms.
  - Above 50 ms, `_schedule_visible_render` (`:1386-1408`) shows a placeholder or the old pixmap scaled, and sends the low render to the client.
  - Below 50 ms the synchronous paint stays.
  - Covers `_render_active_session` and `_rebuild_continuous_scene`.
- **Tests:**
  - `test_immediate_low_paint_async_when_avg_over_50ms`: no synchronous `_render_page_into_scene` on tab switch, F5 or zoom;
  - `test_immediate_low_paint_stays_sync_for_light_docs`;
  - `test_zoom_shows_scaled_previous_pixmap_until_result`;
  - `test_f5_exit_no_gui_raster_when_worker_ready`;
  - `test_async_low_paint_respects_quarantine`.
- **Accept when:** hvac `f5_exit`, heavy `f5_enter` and hvac `tab_switch_high` have `gap_max_ms` < 250, and office `open_first_paint` ≤ baseline + 100 ms.

### Step 5: default `process`, kill-and-respawn preemption
- **Changes:**
  - `render_worker_mode()` defaults to `process` when the variable is unset. The conftest pin from step 1 keeps the suite on `thread`, which closes item 1's step 5 blocker.
  - Preemption: a superseded job that has run longer than `PREEMPT_MS = 1500` while a newer page-lane job waits is killed deliberately (no quarantine, no crash count). The client respawns the child and reloads the document.
- **Tests:**
  - `test_render_worker_mode_defaults_to_process_when_unset`;
  - `test_thread_env_override_restores_inprocess_path`;
  - `test_superseded_job_over_preempt_ms_respawns_and_serves_latest`;
  - `test_conftest_pins_render_worker_thread` (from step 1) still passes.
- **Accept when:** `superseded_wait_ms` p90 < 300 and every earlier gate still passes.
- **Same commit:** the ARCHITECTURE flag default, a PITFALLS entry for preemption, and the TODOS.md:1675 update.

**Later** (after step 5): watermarks in the child (following `src/printing/helper_main.py:46-67`), a display-list cache in the child, on-demand thumbnails for documents over 30 pages, search as a second message type, and `jump_to_result` / single-page mode.

## Decisions
- **D1. One app-wide client in `main.py`, injected into each controller.** It is practical:
  - one constructor keyword;
  - uuid4 session ids keep `doc_key` unique across windows.

  It also settles four review items with a single lifecycle:
  - item 2: one child and one budget for N windows;
  - item 6: one save latch also covers a second window reading the same file;
  - item 10: the quit happens at `aboutToQuit`, so a cancelled close leaves no dead child;
  - item 15: the spawn moves out of the lazy `activate()` (`main.py:227-246`) into `startup_wall`.

  Cost: the child holds one document, so two windows rendering at once evict each other. This is accepted because one window is driven at a time, and it is tracked by `doc_loads`.
- **D2.** The queue lives in the parent, with at most one job in flight and two lanes. The child holds no queue and no pixel cache.
- **D3.** Thread mode is unchanged. With `render_client=None` or mode `thread`, dispatch is exactly today's code (eager capture, `snapshot_bytes`), so existing tests stay valid.
- **D4.** No temp files for pixels or decrypted bytes (R5-01). Passwords travel only in `load_path` bodies.
- **D5.** Quarantine is keyed `(session, page_xref)`. Only `transport_lost` adds a page; edits, timeouts and kills never do.
- **D6.** Keep a change only if its stall metrics meet the step gate and its wall-clock time to content regresses by no more than max(15%, spread).

## Open questions (recommended answer first)
1. Is +150 MB (parent plus child) on the heavy file acceptable? **Yes.** The baseline parent already keeps one full snapshot for clean sessions (`:1280`, cached at `:1063-1072`), which process mode no longer creates; the child's file copy replaces it. Idle child RSS is about 40 MB (unverified; step 2 measures it).
2. Spawn at shell start (deferred after `view.show()`) or at first open? **Shell start.** The child's import overlaps the user's think time, and `startup_wall` gates the cost.
3. Frozen builds? **Thread only** while `sys.frozen` is set, until a packaging spec exists.
4. A second process for thumbnails? **No**, unless step 3's `visible_wait_behind_thumb_ms` gate fails.
5. Keep watermarked sessions synchronous for the whole plan? **Yes**; a follow-up can move them.
6. Should `PREEMPT_MS` be user-visible? **No**; keep it an environment knob.
7. Drop the dirty snapshot cache once it has been streamed? **No.** Search, OCR and preview share it. Revisit with the step 3 RSS numbers.

## Risks
- **Pixel drift** from process-global flags, image-store order (PITFALLS 3414-3418) or a version mismatch. Covered by the byte-equality tests and the `ready` version check (a mismatch switches to `thread`).
- **A clean document read by path can differ from the model's document.** This is the same assumption, with the same stat guard, as today's thumbnail file worker.
- **Decrypted content lives in the child for the whole session.** This is the same exposure as the parent's snapshot cache today.
- **Qt adding `CREATE_NO_WINDOW` for a console-less parent is unverified.** Step 2 checks it by hand under `pythonw`.

## Dead ends and rejected review points
- **Dead ends:**
  - `multiprocessing` (re-imports the main module, needs pickling, breaks frozen builds);
  - line-JSON, base64 or PNG pixels;
  - `QSharedMemory` (needs Qt in the child);
  - holding the user's file open in the child (R7-2);
  - a pool of N workers;
  - a pixel cache in the child;
  - a heartbeat thread in the child (false stalls while `get_pixmap` holds the child's GIL);
  - rewriting `src/printing/subprocess_runner.py` (one job per process; copy its seams only);
  - **a stdin reader thread in the child.** The draft said it was required. It cannot run while `get_pixmap` holds the child's GIL, QProcess writes are asynchronous, and the parent streams a document only while no job is in flight, so a single-threaded loop cannot deadlock.
- **Item 5, fix rejected, diagnosis accepted.** Teaching `_PageRenderWorker` to open the user's file would create a file handle that no save joins, because `_background_file_readers_released` joins only the thumbnail coordinator (`pdf_controller.py:2273-2277`). That brings back R7-2. Replaced by a lazy `snapshot_provider`, called on the GUI thread only when a job falls back to the thread path.
- **Item 11, budget claim rejected; limits and copy count accepted.** "A clean load alone exceeds +150 MB" ignores that the baseline parent already captures a full snapshot for clean sessions (`:1280`), which process mode drops.
- **Item 7, detail corrected; conclusion accepted.** The old `elapsed` was taken before the 20 trailing pumps. The 2-3 s overshoot is a single `processEvents()` that ran past the deadline.
- **Item 1, scope narrowed; fix accepted.** Under D1, controllers built in tests without a client never spawn a child, so the real exposure is the 13 test files that run `main.run` or import `main`. The conftest pin stays as defence in depth.
- **Item 15, premise is specific to the draft.** "`startup_wall` measures nothing" was true of a spawn inside `activate()`. Under D1 the spawn is inside `startup_wall`.
- **Item 19 and the draft's "one real-child test per file".** PITFALLS 1385 concerns live QThread tests interleaved in a Qt loop. Subprocess tests with hard read timeouts are a different hazard, so all of them live in one `_FORCE_QT` file.
- **Item 20, accepted.** The draft's "not measured" was wrong; see the top block.
- **Draft step 0's "kill the worker before `os._exit`"** moved to step 2, because no worker exists in step 0.

## Running log
- 2026-11-05: first measurement (table above). Raw data: `<session scratchpad>/perf/`.
- 2026-11-05 interim re-baseline (n=1, settle cap 120 s, no censored sample; before 0a/0b):
  hvac bg_after_open 22507, tab_switch_high 2718 (p90 5956), bg_after_tab_switch 7520,
  scroll_step_content 257 (p90 2609), sweep 32200, f5_exit 5487; heavy bg_after_open 37511,
  bg_after_tab_switch 19865, scroll_step_content 1365 (p90 1497), sweep 52237. Not the
  step-0 table (no gap metrics yet; n=1).
- 2026-11-05 step 0b landed (subagent): HeartbeatProbe, InputLatencyProbe (poster thread),
  pump durations, timed counters, peak_rss_mb, `gil_probe`; `test_benchmark_stall_probe.py`
  red 6 → 6 pass (one threshold 130 → 110 ms: 20 ms posting period).
- 2026-11-05 step 0c (3 runs; label step0c; raw `<session scratchpad>/perf/step0c.summary.json`).
  Medians ms (office / hvac / heavy): open_first_paint 432 / 908 / 1267; open_high
  456 / 19588 / 1286; f5_exit 89 / 24532 / 131; scroll_step_content 28 / 719 (p90 8944) /
  5047; sweep 2272 / 109619 / 195399; tab_switch_high 46 / 5014 (p90 25658) / 57;
  bg_after_open 643 / 54447 / ≥127456 (censored at 120 s); peak RSS 296 / 618 / 666 MB.
  Worst GUI freeze (gap_max / input_max, ms): hvac open 18214 / 18212, f5_exit 27082,
  scroll 11013, bg_after_open 40364 / 42482, tab_switch 25596; heavy bg_after_open 74986 /
  103642, bg_after_tab_switch 72150 / 90918, scroll 3152.
  gil_probe: freeze ≈ raster (hvac 120 / 133 ms = 0.90; heavy 47 / 50 = 0.94; office 0.95)
  → hypothesis CONFIRMED (≥ 0.8). Heavy censored twice → SETTLE_CAP_S 120 → 300
  (test red → green); heavy re-measured (label step0c_heavy).
  Probes add load (5 ms timer + poster thread needs the GIL): compare only probe-on runs.
- 2026-11-05: the owner approved step 1. Read-only maps produced the design; the GIL claim became step 0's reproducible gate.
- 2026-11-05: an adversarial review (21 items) was checked against the code:
  - items 2-4, 6, 8-10, 12-18, 20 and 21 were folded into the steps;
  - items 5 and 11 were partly rejected, and items 1, 7, 15 and 19 were narrowed or corrected (see above);
  - item 2 was decided as one app-wide client (D1).
  
  The step 0 settle fix was found partly landed in the working tree; the gap it misses (a cancelled thumbnail thread) was added to 0a.

- 2026-11-06: Step 1 foundation implemented; no process client/wiring and no default change. Initial red evidence: protocol/config collected with `ModuleNotFoundError: No module named 'src.render_worker'`; raster with `No module named 'model.page_raster'`; child/infrastructure first run reported `9 failed, 2 errors`. The two errors were sandbox `tmp_path` ACL setup failures; an approved normal-permission run passed. No shims or environment rewrites were added.
- Existing regressions: page coordinator 15 pass; thumbnail coordinator initially `2 failed, 20 passed` because its save-lock instrumentation patched the moved `thumbnail_render_scale`. Adapted that instrumentation to the shared raster entry; `22 passed`. Added exact call/argument assertions; they are supplemental regression guards written after implementation, not claimed as behavior-first red evidence.
- Independent Step 1 review found incomplete warning coverage and an unintended Qt lane for a pure import test. Added explicit pure classification and a broken-xref native-warning case: first `1 failed, 11 passed`, failure `assert b'repair' in b''`. PyMuPDF defaults to suppressing warnings; the test now explicitly enables them in its child bootstrap and injects a native descriptor write. It also disables descriptor redirection as a negative control and requires decoding to fail. Product warning verbosity is unchanged.
- Review boundary reproduction: a JSON integer scale `10 ** 400` produced `OverflowError: int too large to convert to float` (`1 failed, 10 passed`). Validation now converts that into a content-free `ProtocolError`; protocol `11 passed`. Partial-body identity, coalesced multiple frames and individual missing layout fields are covered.
- Normal-permission real-app driver `_evidence_pilot/render-step1/verify_driver.py` under `verify_supervise` exited 0: office 23 pages, End to page 23, Home to page 1, actual zoom 125%, page and thumbnail screenshots inspected. This is thread-path appearance/smoke evidence only, not process responsiveness acceptance.
- Static gates: `mypy model/ utils/` exit 0 (84 files); four selected import-linter contracts kept; code graph regenerated. Suite-runner unit file `198 passed`; benchmark settle `5 passed`. Full-suite and 3-run/3-file performance gates remain unperformed. Step 1 is not labeled fully accepted.
- Independent reviewer follow-up: `ship`, no remaining concrete defect identified in Step 1; no inference of full acceptance. Current-tree ruff and device scan passed; screenshots reviewed at 125%. Detailed evidence is local-only `_evidence_pilot/render-step1/report.md`. No commit/push performed in this session.

- 2026-11-06 Step 2: owner requested app integration plus process-mode measurements. Added one composition-root client, owner-scoped page-priority queue, bounded partial-write transport, lazy clean-path/dirty-snapshot slot, current-identity rejection, bounded startup/render deadline, deliberate cancellation/preemption, crash budget and quarantine, thread fallback, save load hold, accepted-close owner release and independent session release on tab close/detach. Default remains thread; thumbnails and immediate low first-paint remain in the App process.
- Initial scheduler tests collected red (`ModuleNotFoundError: src.render_worker.process_client`), then 6 passed. Later regression guards written after implementation are identified as supplemental coverage rather than blanket red-first evidence. Route tests initially had 3 fixture errors because this repo has no qtbot; replaced that wait with a bounded QApplication loop.
- Runtime-discovered Windows redirector issue: live test red (`worker ready PID != QProcess.processId`, 1 failed), then direct underlying-interpreter launch with CPython's venv hint preserved the same venv and made both PIDs equal. The earlier redirector RSS measurement was discarded. No sandbox-permission shim or ACL change was used.
- Reproduced and fixed shutdown jobs silently discarded (`1 failed, 8 passed`), idle owner's document retention (`1 failed, 14 passed`), save-hold timeout stranding a visible batch and stale respawn PID (`2 failed, 14 passed`), accepted window close not releasing until destruction / shutdown starting pending work (`2 failed, 8 passed`), and idle tab retention / cross-generation RSS loss (`2 failed, 18 passed`). Client final 20 passed; route/controller guards final 11 passed.
- Memory/timing red evidence: a 516-byte PDF requested 536870913 bytes in read instead of 517, and frame duration was 0 under a coarse clock (`2 failed, 16 passed`). Read now uses checked file size plus one; frame duration uses perf_counter. Post-fix process performance was remeasured; pre-fix local artifacts are excluded.
- Validation: real QProcess 200k segments at 4x, byte-equal pixels, maximum inter-tick gap below 100 ms, raster PID ownership and stopped child passed. Existing page coordinator 15, startup 19, multi-tab 118 plus 1 skipped, thumbnail coordinator 22, child 12 and benchmark-settle 5 passed. Full suite remains owner-paused after memory pressure.
- Deliberate bounded deviation: after a page is quarantined, file thumbnails for that session switch to guarded live rendering instead of extending the file request with skip_pages. This is conservative safety; it can reduce healthy-page throughput in a session already affected by a native crash. Quarantine still persists across revisions and is cleared only when the session departs.
- Measurement scope: three fresh visible App runs per file/backend on office/hvac/heavy, backend ready before open, warmed OS file cache. QTest Home/End, actual 125% zoom, 300 ms uncensored background settle, screenshot and child shutdown checks. This targeted navigation sequence is not the full 40-step scroll/fullscreen/tab-switch acceptance benchmark. Wall measurements include ready confirmation/probe teardown; heartbeat/input probes can understate GIL-held stalls, so retain pump_max_ms. Observed child peaks include pre-disposal sampling; the sum of independent parent/child high-water marks is conservative rather than simultaneous RSS.
- Remaining acceptance: full suite, full benchmark scenario gates (including round-trip doc-load bounds), pythonw console-window observation, and broader failure-injection matrix are not inferred from targeted passes. No commit/push in this session. Local detailed results: `_evidence_pilot/render-step1/app-measurements.md` and `summary-app.json`.
- Final Step 2 targeted checks: client 20, routing/controller guards 11, live stress 1, existing page coordinator 15, startup 19, multi-tab 118 plus 1 skipped, thumbnail 22, child 12, benchmark 6 = **224 passed, 1 skipped**. Mypy 84 files clean, four import contracts kept, ruff clean, device scan zero findings, graph refreshed, diff whitespace clean. Independent final reviews: ship for wiring and reporting; no claim of full performance acceptance.
- Final three-run medians (ms; thread -> process), backend ready before open:
  - office: open-high 437.68 -> 404.19; End-high 100.40 -> 120.37; zoom125-high 100.28 -> 100.55.
  - hvac: open-high 5224.98 -> 5740.82; End-high 340.27 -> 300.58; zoom125-high 140.75 -> 140.60.
  - heavy: open-high 1496.66 -> 3061.45; End-high 500.26 -> 100.77; zoom125-high 100.42 -> 300.80.
- Process frame-GUI per-run p95 medians office/hvac/heavy: 6.10/5.99/5.41 ms; office worst per-run p95 8.79 ms, so not every run meets the <8 ms gate. Parent+observed-child independent peak medians (MiB): office 351.1+63.3; hvac 591.0+143.8; heavy 712.0+75.0. Thread parent medians: 356.2/628.3/723.8. This is an upper-bound sum of independent peaks, not simultaneous memory.
- Background-after-open process pump-max medians remain 11.18 s on hvac and 21.14 s on heavy (thread 7.08/17.04 s); input-latency maximum medians 11.54/23.96 s. Moving only background page raster did not solve overall responsiveness. Keep thread default; do not label the speed item OK.
- All nine final process App runs consumed IPC images, confirmed Home/End and 125%, closed the last tab through Ctrl+W with document dropped/window owner retained, then confirmed stopped child. Three representative 125% screenshots inspected. Error-fallback counter is zero in these healthy runs; it does not count the separate not-ready thread path, which remains available after preemption. Official office benchmark (one process run, complete existing scenario sequence) exited 0: doc loads 3, IPC 43360238 bytes, frame-GUI p95 4.1 ms, observed child peak 69.4 MiB. It is a separate offscreen harness run, not a comparable cold-boot sample.
