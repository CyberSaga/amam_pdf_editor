# B7 progress (owner go-ahead 2026-11-26 "開始 B7"; plan A; Astra quota reset 11-27 00:5x, review in flight)

## Current state (at most 40 lines)
- Branch feat/true-text-edge-cases, HEAD 4f608d04; nothing committed by me (owner commits). ruff clean, mypy model/ utils/ clean.
- Whole suite at step-1 point: 17385 passed, 1 failed (test_worker_snapshot_cache, fixed since), 0 hung. Vector/OCR/undo subset after
  steps 1,3,4,6,7: 3986 passed, 8 skipped. A fresh whole-suite run is still owed before any commit.
- Step 1 write gate DONE (advisor-reviewed; Astra review pending): model/write_gate.py, PDFModel.write_gate/write_transaction/
  submit_ocr_page/drain_pending_ocr/commit_vector_plan(lease=), CommandManager gate + lease=, tools gated (annotation, watermark),
  controller _live_only busy guard + OCR coordinator submit/drain. Tests test_vector_write_gate.py (+_controller).
  GAP: no production flow calls write_transaction yet (controller vector_delete flow does not exist); main.py closeEvent/CLI not gated.
- Step 2 plan-A history: covered by test_write_transaction_defers_ocr_until_after_the_history_record_and_undo_drops_it.
- Steps 3+4 dots: VectorIndex.dots (24 B, path/subpath ordinal/x/y), G + F scanners byte-identical, transport validated,
  click/touch/delete chain proven by pixels (test_vector_dots.py, 41 tests). Deviations from Astra: unknown cap (gs) never stored;
  only stroke paints; path needs >=1 prim (lone "m h" paints nothing); model-side /LC resolution NOT done.
- Step 5 CLIPPED: draft only (plans/b7-clipped-design-draft.md), no code.
- Step 6 skipped mask DONE (_countable in index.py; test_vector_skipped_mask.py).
- Step 7 model half DONE (movable_count, supports_move = movable subset, vector_selection_presentation + utils/vector_selection_dto.py,
  dots in presentation). View/Controller half NOT built: no sig_vector_select/set_vector_selection exists anywhere in view/controller.
- Open: 50 ms click gate on the real 414k-row CAD page with dots (re-run test_cad_sample_click / benchmark), docs (ARCHITECTURE,
  PITFALLS, TODOS), /verify, plan-code-reviewer for >3 files before commit.

- Astra review a (plans/b7-review-astra-a.md) FIXED so far: failed transaction no longer drains OCR; lease must be the live holder; queued OCR carries a page key (xref, rotation, rect, cropbox) and goes Stale on change; model hook on_ocr_applied wired by OcrCoordinator.connect_bridge; selection never lent across index objects; skipped stored per token and shared by Info/DTO ('all' now counts skipped); resize_object gated; _READ_ONLY_SLOTS shrunk; click gate: per-index query cache, real CAD page 414,510 rows click median 10.7 ms, max 33.2 ms (first call builds the cache), box 13 ms.
- Astra review a NOT fixed (open, owner/next round): real subpath ids for zero-length l + fill/butt rows that click but paint nothing; gs-resolved /LC,/LW candidates; sparse transport ordinal; T0/T1 session/handle/revision recheck and the damaged-latch outcome type; main.py closeEvent / CLI open / live-handle readers (search, render, text preview) not gated; per-UI-turn OCR apply; saved_ocr_state for dirty; vector undo/redo lease; View drawing + controller delete flow absent.
- Checks after fixes: ruff clean=true, mypy model\pdf_model.py:4413: error: Argument 1 to "append" of "list" has incompatible type "tuple[str | None, int, tuple[Any, ...], tuple[Any, ...] | None]"; expected "tuple[Any, int, tuple[Any, ...], int]"  [arg-type]
model\pdf_model.py:4539: error: Value of type "Any | None" is not indexable  [index]
Found 2 errors in 1 file (checked 104 source files); vector/OCR/object/multi-tab subset 4603 passed, 9 skipped.

- Astra round 2 (plans/b7-review-r2.md): Part A open: commit returning None still drains (publish must be explicit: record(cmd, lease) = publish), OCR key proves page only at delivery not at recognition, jump_to_result/change_page still render live doc, vector_selection_segments/mask read an unvalidated mask, _query_cache resident ~21 MiB per 414k-row index not counted in LRU and should be built at install_vector_index, gate inventory still hand-kept (class-level outcome test designed in r2). Part B (CLIPPED) completed as a design: measure CAD corpus first (B5 baseline: only 22060_A1 p1 and hvac p1 have candidates; ecc/hvac p6 gain 0), single axis-parallel rect, clip_rects/clip_limits tables, G/F parity incl. cumulative intersection, 7 red-light steps. Owner decision: build it only if the corpus census shows gain.
- Post-suite2 batch DONE 02:3x: lease.published (record(cmd, lease) = publish; a transaction without it never drains), FIFO submit, latched session never drains, query arrays warmed in install_vector_index and counted in the LRU (resident 21.0 MiB per 414k-row index), selection readers validated (read-only mask view), transport docstring six tables.
- Latency (CAD before.pdf p1, 414,510 rows, click via PDFModel.vector_select, idle machine): 0 dots blank max 11.1 / hit max 25.1 ms; every row one dot blank 17.9 / hit 39.4; all rows countable-only (fall-through) blank 18.6 / hit 36.8; every 2nd row countable hit 25.8. All four max < 50 ms (single run each, 43 clicks); install_vector_index 18-19 ms.
- Suite2 (before the post-suite batch): 17464 passed, 0 failed, 17 skipped, 0 hung. Suite3 on the final tree pending.

- 02:45 gate inventory is now DERIVED: test_vector_write_gate.py writer_candidates() walks PDFModel/AnnotationTool/WatermarkTool for public methods reaching fitz mutators or delegating with self; each must be gated or explained in NOT_A_WRITE_ENTRY (reasons). Lifecycle (open_pdf, close, close_session, close_all_sessions, import_session_transfer) now gated. Known limit: delegation through modules that do not receive self (WatermarkTool.on_session_open -> strip_marked_watermarks) is not derived.
- Astra quota ran out again 02:44 (resets 05:44); round 3 (astra_r3.prompt in scratchpad) to be re-run after that. Suite3 started 02:43 on the final tree (log in scratchpad suite3.log).

- SUITE3 (final tree, 04:11): 17475 passed, 0 failed, 17 skipped, 0 xfailed, 0 errors, 0 hung, 0 crashed. ruff clean, mypy model/ utils/ clean. No source edit after suite3 started.
- Owner decisions for 07:00: (1) View/Controller wiring for vector selection + the vector_delete flow (no sig_vector_select exists): B7 scope or separate card? (2) subpath stores a per-path dot ordinal, not the real subpath id (tests pin it); real ids needed for zero-length l fixes. (3) resolve /LC and /LW from gs on the Model side? (4) build CLIPPED only if the corpus census shows gain (plans/b7-clipped-design-draft.md + r2 Part B). (5) the OCR-layer-survives-undo card (clear-OCR first). Nothing is committed.

- Astra round 3 (plans/b7-review-r3.md, 05:50): verdict = do NOT wire the production vector_delete flow yet. Same mechanism for the third round (entries outside the gate); per the review-recurrence rule NO further instance patches were made. Class fix proposed: controller integration test firing every queued entry from the T0/T1 on_yield + revalidating (session, handle, revision) after each yield. Open instances: CLI open switches session inside the pump (pdf_controller.py:2106), whole-window close (closeEvent/handle_app_close), direct submit_ocr_page on a latched session, vector_plan_inputs hands out the raw mask, after-capture/record failure inside write_transaction, WatermarkTool.on_session_open and pdf_object_ops free functions not derived.

## Log
- 15:09Z step 1 green; 16:40Z suite result; 16:43Z steps 3/4/6/7 green; 16:44Z Astra review launched (scratchpad astra_b7a.out).
