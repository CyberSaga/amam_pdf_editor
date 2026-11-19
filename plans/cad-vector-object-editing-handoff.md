# Handoff: CAD vector object editing, executable without Fable

<!-- Written 2026-11-17 by Fable for Opus / Sonnet / Haiku. Design source: plans/cad-vector-object-editing.md (revision 11 + two review logs in its section 16). Second edition the same day: every design choice is now written here by Fable. -->

## Current state / next step (≤40 lines)

- **What this file is.** The work of `plans/cad-vector-object-editing.md` (the "design plan") cut into task cards. Each card names the model, what to read, the design (modules, functions, data, order of calls), the red tests, how it is accepted, and when to stop. Where this file and the design plan disagree, **this file wins**; the known stale passages of the design plan are listed under "Design plan text that is void".
- **Owner rulings (2026-11-17).** (1) The M0 cut and the test-first approach are agreed; there is no revision 12 on paper. (2) **Sonnet may read this file and the design plan side by side, but Sonnet never decides architecture or design. All of it is supplied here by Fable.**
- **Rules for every card.**
  1. **No open design choice.** A card fixes module, function names, signatures, data shapes, thread, wording of messages and what happens in each outcome of a measurement. If an implementer meets a choice that is not fixed here or in the design plan, it **stops and reports the question**; it does not choose, and Opus does not choose for it either: the question goes to the owner (who may bring it to Fable). A deviation forced by a failing test is reported the same way.
  2. Red light first, then code. No design review rounds on paper.
  3. A number that closes a gate is measured through the product's own function (`model.doc_bytes` imported). Otherwise it is a "library fact" and closes nothing.
  4. Nothing may block the GUI thread long enough to look frozen. A wait is fine if the window stays live and says what it is doing.
  5. CLAUDE.md applies in full (one pytest at a time, `.venv\Scripts\python.exe`, ruff clean, commit only when asked, no machine paths in tracked files).
- **Model roles.** Sonnet (`implementer`): every card, exactly as written. Haiku (`Explore`, `log-reader`): locating code, reading test output. Opus: runs the session, checks each card against its "Accept" lines, and adjudicates Codex's findings (H23). Opus does **not** write design; where a card says "decision rule", the rule is applied mechanically to the measured number.
- **Order.** Track A (M0): A1, A2, A3, A4, A5. Track B (M1): B1 to B8, after A5. Track C (M2): C1 to C3, after the owner has seen B8. One card at a time (one pytest at a time). **How to start: section "Kickoff" at the end.**
- **Owner decisions (2026-11-17, evening), all settled.**
  - Q1. The commit stall limit (gate B3) is **1 s**, with a busy cursor.
  - Q2. No document is refused for the *time* its integrity check takes. The check is measured on the document itself, never estimated from megabytes; a slow check runs in slices with the window live and a progress line (H22).
  - Q3. Reviews are done by **Codex** (the defensive reviewer); **Opus** accepts or rejects each finding in writing (H23).
- **Not reviewed.** H1 to H23 and the card designs below were written by Fable and have not been through an independent review. They are closed by their red tests, not by argument: a test that contradicts a card is a stop, not a reason to improvise.
- **Status (2026-11-19).** A1 to A4 committed. A5 is in the tree, not committed. Owner ruled D1 to D12 (running log, 2026-11-19; records `plans/archive/cad-owner-decisions-*.md`). D1 is fixed in the tree (not committed). **Next, in order: Opus card for D12, then D12, D4, D9, D10, D3, D6, D2 (+N3), D11, D7 card text; then the A5 review and commit; A6 card (Opus design) before Track B.**

## Decisions fixed here (they close the open review findings)

Finding numbers: "O-" = Opus review of 10a, "C-" = Codex review of 11 (design plan, section 16).

- **H1. Scratch copies never touch the source (C-B1).** Measured on 150 annotated pages of `test_files/`: `insert_pdf` changed objects of the source document on 103 pages with default arguments, on 14 with `annots=False`, on **0 with `annots=False, links=False, widgets=False`**. Every read-only scratch copy uses those three arguments, and a test proves non-mutation with a digest of every object before and after (card A2).
- **H2. No persistent helper, no 2 GB reservation (C-M3).** Background work is a one-shot `QProcess` per job (the shape of `controller/recent_file_probe.py`). The job kinds and the protocol are H16.
- **H3. Cache keys include the page frame (C-M2).** A cache of page geometry is keyed on `(model.handle_generation, page_num, model.content_revision, len(doc), page.rotation, tuple(page.cropbox), tuple(page.mediabox))`. One function builds it: `table_objects.frame_key(model, page_num)`. **Amended by owner decision D1 (2026-11-19):** the first field was `id(doc)`, which CPython reuses after a handle is closed (A3 review B2). `handle_generation` is process-unique, taken afresh in the `PDFModel.doc` setter whenever a live handle is installed or replaced, and never restored by undo or a round trip (unlike `xref_epoch`). When a handle is replaced or its session closed, the results of every generation no tab holds are dropped at once (`table_objects.retire_dead_handles`); other tabs keep theirs. A late tables answer of any status (a crash included) for a key that is no longer current is dropped silently and never retried. No document identity anywhere in M0/M1 uses `id(doc)`. **Amended again 2026-11-19 (owner, D1 review finding A):** the revision field was `edit_count`, which undo and redo never change and a save resets; it is now `model.content_revision`, a pair that takes a never-repeated value from one process-wide counter (`edit_commands.next_revision`) on every write of `edit_count` and on every execute, record, undo and redo of the command manager. A document change that does neither is still a gap; `test_frame_key_revision.py::test_a_changed_page_never_keeps_its_frame_key` is the class check, and each new kind of document change adds itself to its operation list.
- **H4. A pending click is data, not a replay (C-M2).** It stores the page number, the point in visual page coordinates, the Shift state, the mode and a generation number. The generation changes on: any newer press in the view, a mode change, a document or tab change, a selection change. The result is applied only if the generation is unchanged. Scroll and zoom do not cancel it.
- **H5. GUI-thread work is measured, not argued (O-X1, C-M1, C-m1).** The harness of card A3 runs a gesture to **completion** with a 0 ms `QTimer` heartbeat and reports the longest gap and whether the gesture finished. Limits: 100 ms for click, right-click, mode entry, marquee; B3 (Q1) for commit and undo. Native dialogs are not part of any gesture.
- **H6. Rule A: the builder never interprets bytes (O-M8, C-M6).** A mutant is defined on the builder's abstract scene, and the builder emits bytes and facts for that wrong scene the same way it does for the correct one. A cell is must-kill when the mutant's facts differ from the correct facts inside the oracle's declared domain. Equivalent means equal facts. A mutant whose differing fact is in no oracle's domain fails the run.
- **H7. Matching (C-M7).** Records are quantised to the tolerance grid and compared as multisets first. Only records within one tolerance of a cell edge go to component matching; a component over 5,000 candidate edges fails the test with "ambiguous fixture".
- **H8. Rule B at run time (O-M4 to M6, C-M4, C-M5).** No table is kept across commits. Inside the guarded commit step, on the GUI thread: capture the snapshot, digest pass (T0), write, digest pass (T1), compare against the declared write set. T0 and T1 are stored on the undo command. After a rollback or an undo the restored document's table must equal T0; after a redo, T1. The digest: per object, a 16-byte BLAKE2b of the object text plus raw stream bytes; file containers (`/Type /ObjStm`, `/Type /XRef`) as one class; `/Length` left out of a stream's text; a page object as two hashes (`/Contents`, the rest); one entry for the trailer keys other than `/ID` and `/Size`. A mismatch after a restore turns vector editing off for that document in this session, with a message; other tools keep working.
- **H9. Eligibility at mode entry (O14) is a preflight only.** Two conditions: capturing a snapshot leaves the live table unchanged; the reopened snapshot's table equals the live one. A document that fails either is refused (its structure changes on save). The time of a pass is **not** a condition (H22). H8 checks each commit by itself.
- **H10. F's number parser (O-m1, C-M8).** The vector parse takes a token only if it is digits with an optional sign and one optional point, at most 15 digits in total. Everything else goes through Python `float()`.
- **H11. Flags (O-M7).** The open-path bit is a forward fill over construction and paint events. `IN_OC` comes from `BDC`/`EMC` pairing by marked-content depth. Neither uses the `q` level pass.
- **H12. Provenance guard records the callable (C-M9).** The gate table stores, for each number, the qualified name of the function that was actually called, captured at run time by the measuring script.
- **H13. Deferred, on purpose.** The inline-image proof (after M1, O9): in M1 every inline image stops the scan. Accelerator F is built only if the rule of card B3 says so.
- **H14. A cold analysis never blocks and never replays an edit.** Two cases. *Lookup* (click, right-click): the model answers "pending", the job starts, the click is kept as data (H4) and resolved when the answer arrives. *Edit* (move, resize, rotate, delete, insert image, delete table) on a page whose analysis is cold: the controller **refuses the edit, starts the job and says so in the status bar**; when the job ends the status bar says the page is ready and the user repeats the gesture. The edit is not queued and not replayed, so the selection frame (the D-OBJ-FRAME rule) and the undo stack never see a half-done operation.
- **H15. Model functions stay blocking; the controller keeps the GUI off the slow path.** `get_object_info_at_point`, `table_rects`, `discover_native_image_invocations` keep their signatures and block when called directly (tests, scripts, the merge CLI). The GUI goes through the controller methods of A3 and A5, which ask the model "is it ready?" first. No flag on the model switches behaviour.
- **H16. One child, three job kinds, one protocol.** Child kind `object-probe` in `src/render_worker/launch.py::_CHILDREN`: module `src.object_probe.helper_main`, frozen flag `--object-probe`, dispatched in `main.py` like `--print-helper`. Input on stdin: one UTF-8 JSON header line `{"v":1,"kind":K,"sizes":[n1,…]}` then the payloads concatenated, then the write channel is closed. Output on stdout: one JSON line, then exit code 0. Any other exit code or unparsable output is a failure. Kinds: `tables` (payload: one one-page PDF; answer `{"v":1,"rects":[[x0,y0,x1,y1],…]}`), `scan` (A5; payloads: decoded content streams; answer `{"v":1,"scans":[…]}`), `digest` (B6; payload: a snapshot; answer `{"v":1,"table":…}`). The child imports only what its kind needs (`fitz` for `tables` and `digest`; `scan` imports `model.content_scan` only).
- **H17. Native-image edits become byte splices (A5).** Today they tokenise the whole stream and re-serialise every token. From A5 on, a matrix rewrite replaces only the bytes of the `cm` operands and a delete removes only the bytes of the `Do` (or of its `q…Q` block). This is required for speed and is also more faithful (comments and inline images are no longer re-serialised).
- **H18. A scan result is keyed by content, so it survives undo and never goes stale.** `StreamScan` is a pure function of the decoded bytes; its cache key is the BLAKE2b of those bytes. `add_image_object`, undo, redo and saves need no invalidation hook (this is what O-M1 objected to in a revision-keyed cache).
- **H19. Move operands (replaces "six decimals").** For a translation written under a linear part `L` (2×2), the number of decimals is `d = clamp(ceil(log10(5000 · s)), 0, 12)` with `s = max(|L00|+|L10|, |L01|+|L11|)`, so the error in page space is at most 1e-4 pt. Trailing zeros and a trailing point are stripped. `L` is the path's full CTM for D8b and the outer CTM for D8a.
- **H20. The vector selection is one mask in the model.** `VectorSelectionInfo.token` is an integer that the model increments on every selection change; the model keeps only the latest `(token, page_num, index_key, mask)`. A request with any other token is refused as `VECTOR_SELECTION_STALE`.
- **H21. Scanner placement (rule in B3).** G and F run in a `QThread` worker of the coordinator, bytes in and tables out. If the heartbeat gap during the scan exceeds 100 ms, the scan moves to the one-shot child (kind `vector-scan`, same protocol, arrays returned through one `numpy.save` file in the app's temp directory whose name the child prints; the parent loads and deletes it). Nothing else changes.

- **H22. The integrity check is paid in time, never by refusal (owner, Q2).** "One pass" is one run of `digest_table` over **every object of the whole document** (not one operator, not one page). It is needed twice per edit (T0 before the write, T1 after), on the GUI thread, because only that thread may read the document. Its time is measured on the document at mode entry and again on every commit; megabytes are never used. Measured so far: 133 to 215 ms on 36 to 47 MB files with about 10,000 objects.
  - *Fast documents (last measured pass ≤ 400 ms):* both passes run in one piece; snapshot, two passes and the write fit the 1 s of Q1. Nothing else can run in between.
  - *Slow documents (last measured pass > 400 ms):* both passes run in slices. `digest_table(..., on_yield=cb)` calls `cb(done, total)` every 50 ms of work; the controller's callback shows 「正在確認文件其他部分未被更動… n %」 and calls `QCoreApplication.processEvents(QEventLoop.ExcludeUserInputEvents)`. The window repaints and never shows 「沒有回應」; mouse and keyboard input waits until the commit ends. At mode entry such a document shows once: 「此文件的物件很多，每次編輯後需要約 n 秒確認文件完整性」.
  - *Guard for the slices.* Timers and queued signals still run during a slice. The model records `(model.handle_generation, model.content_revision)` (H3 as amended 2026-11-19; never `id(doc)` or `edit_count`) before each sliced pass and compares after it. Changed during T0 (nothing written yet): refuse with `VECTOR_SELECTION_STALE`. Changed during T1: the edit stays, the comparison is skipped, and vector editing is latched off for the document with 「文件在確認期間被其他作業更動，本次工作階段已停用向量編輯」 (restoring the snapshot would destroy the other change). Card B6 lists every timer- or signal-driven caller that writes or serialises the document; its stop line applies if one exists.
- **H23. Review protocol (owner, Q3).** After A5 (all of M0), after B6, after B8 and after C3, Codex reviews the diff of that stretch, run the way the design plan's revision 11 review was run. Opus then writes, per finding, **accepted** (it gets a red test first, then a fix inside the card's design) or **rejected** (one line of reason: not reachable, already covered by a named test, or outside the card). A finding that can only be fixed by changing a design in this file is neither: it is a stop under rule 1. The table of findings and verdicts goes into the running log. One round per stretch; a second round only on the owner's word.

- **H24. Hard memory cap on the object-probe child (owner, 2026-11-18; replaces A3's "stop above 1,024 MiB").**
  - The formula: `C = round_down_to_64_MiB(min(1728 MiB, total physical RAM / 8, max(0, min(avail_phys, avail_commit) - max(1 GiB, total_phys / 16)) / 2))`.
  - It is enforced as a Windows Job Object memory limit on the child.
  - The 1,728 MiB ceiling is the measured peak commit (1,341.5 MiB, Codex/gpt-6-astra advisory) × 1.25, rounded up to 64 MiB.
  - The charge recorded in the ledger is not the safety mechanism.
  - The no-text preflight, the typed outcomes and the rule that a failure never caches `[]` are fixed in card A3b.

## Design plan text that is void

Step 1 and Step 1b of §10 (persistent helper, `probe_page`, `model/object_probe.py`): replaced by A1 to A5. §7.1 rows for `model/object_probe.py` and the helper: replaced by A3. §7.3 "helper process for the reopened copy": H16 kind `digest`. D23 "one table is kept per document revision": H8. D25 and §11 "150 ms" and "500 ms": 100 ms and Q1. Eligibility condition (3) "one pass at most 400 ms" and the sentence 「此文件的物件數量過多，無法進行向量編輯」: removed by H22. "Six decimals" in §9: H19. "§4.2 P13 bit-equal to G": only B4's test decides. `ObjectLookup` cache key `(id(doc), page, edit_count, len(doc))`: H3.

## Track A: M0, the click freeze

### A1. Sonnet. Image discovery returns at once on a page with no image
- **Read:** `model/pdf_content_ops.py:350-442` and the form path after it.
- **Do:** in `discover_native_image_invocations`, directly after `page = doc[page_num - 1]`: `if not page.get_images(full=True): return []`. Nothing else.
- **Red first:** `test_scripts/test_object_click_on_vector_page.py`: with `model.pdf_content_ops.parse_operators` patched to raise, a synthetic page with 20,000 paths and no image returns `[]` (today it raises); a page with one image and a page with a form-nested image return lists equal to the ones recorded before the change (compare all fields).
- **Accept:** the test passes; `test_scripts` object tests pass; ruff clean.
- **Stop:** if any existing test depends on discovery running on an image-free page.

### A2. Sonnet. The table probe stops changing the user's document, and its cache follows the page frame
- **Read:** `model/table_objects.py`; `model/pdf_model.py` `rotate_pages`; `plans/cad-vector-object-editing-probes/p17_object_digest_cost.py` (`digest_table`, `differing`).
- **Do, all in `model/table_objects.py`:**
  1. `frame_key(model, page_num) -> tuple` per H3 (reads `model.doc[page_num - 1]`).
  2. `scratch_page_bytes(doc, page_num) -> bytes`: `fitz.open()`, `insert_pdf(doc, from_page=p, to_page=p, annots=False, links=False, widgets=False)`, `tobytes()`, close.
  3. `find_table_rects(page) -> list[tuple[float, float, float, float]]`: the loop that is inside `table_rects` today (row and column minimum, sheet-frame filter), unchanged, exceptions caught as today.
  4. `table_rects` = cache lookup by `frame_key`; on a miss `find_table_rects(fitz.open(stream=scratch_page_bytes(...), filetype="pdf")[0])`, then store. Stale entries are those whose first four key fields differ from the current ones, as today.
  5. `cached_table_rects(model, page_num) -> list[fitz.Rect] | None` (no work; `None` on a miss) and `store_table_rects(model, key, rects) -> bool` (stores and returns `True` only if `key == frame_key(model, key[1])`).
- **Do not change** the other scratch copies. They are listed here for the owner, found by Fable: `model/tools/manager.py:276` and `:311`, `model/watermark_raster.py:71`, `model/text_paint_state.py:932` (`model/navigation_graft.py:721` is a real insert, not a scratch copy). Check each with the digest test and add the result to this card; fixing them is a separate task.
- **Red first:** `test_scripts/test_table_probe_non_mutation.py`: on three annotated fixture pages (one with a link, one with a widget, one with a text annotation), the digest of every object of the source is equal before and after `table_rects` (fails today); after `rotate_pages` the cached rectangles are not reused; tables found on the existing table fixtures are unchanged.
- **Accept:** tests pass; a `docs/PITFALLS.md` entry ("`insert_pdf` mutates the source's annotation objects unless `annots`, `links` and `widgets` are all off") plus index regeneration.
- **Stop:** if dropping annotations changes which tables are found on any existing fixture.

### A3. Sonnet. The table probe leaves the GUI thread
`find_tables` takes 12.6 s on the sample page (0 tables). After A1 it is the whole remaining freeze.

**Read:** `controller/recent_file_probe.py` (copy its process handling), `src/render_worker/launch.py`, `main.py:10-56` and `:430-470`, `view/pdf_view.py:4560-4660` (press path) and `_show_context_menu`, `view/object_selection.py:146-168`, `controller/pdf_controller.py:3305` and `:3361-3530`, `test_scripts/test_child_launch_guard.py`.

**Design.**
1. *Child.* `src/object_probe/__init__.py` (empty) and `src/object_probe/helper_main.py` with `main() -> int`: read the header line and payloads from `sys.stdin.buffer` (H16); for `tables`: `doc = fitz.open(stream=payload, filetype="pdf")`, `rects = model.table_objects.find_table_rects(doc[0])`, print the answer, return 0. Register the kind in `_CHILDREN` and add `_object_probe_entry` plus the `--object-probe` dispatch line in `main.py`, before any Qt import, exactly like `--print-helper`. Update the launch guard test.
2. *Model, non-blocking lookup.* `model/object_requests.py` gets `class ObjectLookupPending` with a module singleton `OBJECT_LOOKUP_PENDING` and a field-free `__repr__`. `pdf_object_ops.get_object_info_at_point(model, page_num, point, *, blocking: bool = True)`: unchanged when `blocking`; when not, the table step uses `cached_table_rects`; on `None` it returns `OBJECT_LOOKUP_PENDING` (only after the annotation and native-image steps found nothing). `PDFModel.get_object_info_at_point` passes the keyword through.
3. *Two classes: the process is App-wide, the logic is per controller* (the service loop at `main.py:466-471` expects an App-wide object with `_process`, `shutdown()` and `stopped`, like `RecentFileProbe`).
   - **`controller/object_probe_runner.py`, `class ObjectProbeRunner(QObject)`**: knows nothing about PDFs. `for_app(app, *, ledger=None)` as `RecentFileProbe.for_app` (attribute `app._pdf_object_probe`); created and added to the service tuple in `main.py` beside `recent_probe`, so nothing is started in `PDFController.__init__`. `submit(owner: object, kind: str, payloads: tuple[bytes, ...]) -> int` (job id; starts at once if idle, else waits in a FIFO), `cancel(job_id)`, `cancel_owner(owner)` (queued jobs dropped, a running one killed). Signals `finished(int, object)` (job id, parsed answer dict) and `failed(int)`; `stopped()`. One process at a time: `QProcess`, `child_launch('object-probe')`, `prepare_owned_qprocess_start()`, header and payloads written in `started`, then `closeWriteChannel()`; stdout collected until `finished`; **no size cap and no timer**. Lease per process: `ledger.try_reserve('object-probe', 'process', OBJECT_PROBE_CHARGE, required=True)`, released as in `RecentFileProbe._release_lease`. `shutdown()` as `RecentFileProbe.shutdown`. A constructor argument `process_factory` (default `QProcess`) lets tests inject a stub.
   - **`controller/object_probe_coordinator.py`, `class ObjectProbeCoordinator(QObject)`**, created in `PDFController.__init__` next to `_search_coordinator` with the model; it fetches the runner lazily (`ObjectProbeRunner.for_app(QApplication.instance())`) on the first request. Signals: `tables_ready(int)` (page number), `probe_failed(str, int)` (kind, page number).
   - `request_tables(page_num)`: `key = frame_key(...)`; return if cached, or if a job with the same key is running or waiting; else `payload = scratch_page_bytes(...)` (GUI thread), cancel this coordinator's waiting `tables` job if any (a newer request replaces a waiting one; a running one is left to finish), and `submit`. It keeps `Job(kind, page_num, key, payloads, attempt)` per job id.
   - On `finished`: `store_table_rects(model, key, rects)`; if it returned `True` emit `tables_ready(page_num)` (a stale key is dropped silently). On `failed`: `attempt == 1` → submit the same payloads again as `attempt=2`; else `store_table_rects(model, key, [])` and emit `probe_failed("tables", page_num)`.
   - `cancel_all()` = `runner.cancel_owner(self)` and forget the jobs. Called from `PDFController.release_render_owner`, `on_tab_changed` and `on_tab_close_requested`.
   - `OBJECT_PROBE_CHARGE` in `src/render_worker/admission.py`. **Decision rule:** write `plans/cad-vector-object-editing-probes/p19_probe_child_memory.py`, which starts the child on each stall fixture and on the sample when present and reads the peak working set; the constant is that maximum plus 8 MiB, rounded up to a multiple of 32 MiB, with the measurement in its comment. If it exceeds 1,024 MiB: stop.
4. *Controller.* `lookup_object_at_point(page, point)`: `info = model.get_object_info_at_point(page, point, blocking=False)`; if pending, `self._object_probe.request_tables(page)` and `view.set_status_bar_override_message("正在背景分析此頁的表格，完成後會自動選取…")`; return `info`. `object_op_ready(page_nums, kinds) -> bool`: `True` unless a kind is `table` and `cached_table_rects` is `None` for its page; then it requests the job, shows 「正在分析此頁的表格，完成後請再操作一次」 and returns `False`. `delete_object` calls it first and returns without a dialog when it is `False`. Slots: `tables_ready` → clear the status message, `view.resolve_pending_object_click(page_num)`; `probe_failed` → status 「此頁的物件分析失敗（第 n 頁）」 and `view.drop_pending_object_click()`.
5. *View.* `get_object_info_at_point` stays for tests. The press path (`pdf_view.py:4606-4660`) and `_resolve_object_info_for_context_menu_pos` call `controller.lookup_object_at_point`.
   - Extract the selection block (lines 4610 to 4649) into `ObjectSelectionManager._apply_object_hit(page_idx, object_info, additive) -> bool` with no behaviour change; the press path calls it and then arms the drag as today.
   - State on the manager: `_object_click_generation: int`, `_pending_object_click: PendingObjectClick | None` (dataclass in `view/object_selection.py`: `page_num, x, y, additive, mode, generation`). The generation is incremented at the top of every left press, in `set_mode`, in `_clear_object_selection` and in `_select_object` (the controller's `_drop_object_selection` and the tab handlers reach `_clear_object_selection` already; a red test pins that a tab change drops the pending click).
   - Press path on pending: store the pending click (after the increment), accept the event, arm nothing.
   - `resolve_pending_object_click(page_num)`: if a pending click exists for that page with the current generation and mode, call `lookup_object_at_point` again; a hit goes to `_apply_object_hit` (no drag armed); pending again keeps waiting; `None` clears it. `drop_pending_object_click()` clears it.
   - Context menu: `_resolve_object_info_for_context_menu_pos` returns the string `"pending"` in that case; `_show_context_menu` then adds one disabled action 「正在分析此頁物件…」 in place of the object entries and does not select. The menu is not reopened later.
   - `_delete_selected_object` calls `controller.object_op_ready(pages, kinds)` before it emits; on `False` it returns `False` and keeps the selection.
   - A press on a resize or rotate handle, and a drag of an already selected object, do no lookup today (they return before line 4606); a red test pins that.
6. *Docs.* `docs/ARCHITECTURE.md`: the fourth helper process, the coordinator, H14 and H15.

**Red first.** `test_scripts/test_object_probe_runner.py` (Qt, stub process): FIFO order, cancel of a waiting and of a running job, the lease taken and released, shutdown with a running child. `test_scripts/test_object_probe.py` (Qt; stub runner): a cold click returns pending and stores the click; the answer selects the object; a changed generation or key drops it; a second click on another page replaces the queued job and does not kill the running one; a failed child is retried once, then the failure message and an empty cached list; the menu content while pending; delete of a table on a cold page is refused with the selection kept; `PDFController.__init__` starts no process. `test_scripts/test_object_probe_child.py`: the real child on a table fixture returns the same rectangles as `table_rects`. `test_scripts/test_gui_stall.py` (H5 harness in `test_scripts/gui_stall_probe.py`: `run_gesture(app, gesture, done) -> (max_gap_ms, finished)`): fixtures built in the test: a page that is only `/Fm0 Do` with 200,000 paths in the form, a 200,000-path page, a page with three 4,000 × 4,000 images.

**Accept:** every gesture in the stall test (left click in 操作物件, right-click in browse, objects and text-edit modes) finishes with a longest gap of at most 100 ms. (The review of M0 is the Codex round after A5, H23.)

**Stop:** if `scratch_page_bytes` alone takes over 100 ms on any fixture; if the charge rule says stop; if a GUI-thread caller of `table_rects` or `matching_table` exists other than the click, the menu and `_delete_table_object`.

### A3b. Sonnet. Memory cap, text preflight, typed outcomes (amends A3; owner 2026-11-18)

A3's code is in the tree, uncommitted. This card fixes the two Stops A3 raised and is accepted together with A3 as one commit. The owner ruled on both:

- **(1) Child memory.** The fixed charge is replaced by H24's cap, enforced by the operating system. Background: Codex's advisory (gpt-6-astra) measured the sample at 1,341.1 MiB peak commit, 412,529 paths, 710,205 edge dicts and 0 characters.
- **(2) The six gestures over 100 ms** go to A5. `KNOWN_OVER_LIMIT` in `test_gui_stall.py` stays as it is.

"Table" here means PyMuPDF's `find_tables` table object (select or delete a whole ruled grid). It is not line editing: that is Track B, which never calls `find_tables`.

**Read:** H16, H24; `model/table_objects.py:86-152`; `src/object_probe/helper_main.py`; `controller/object_probe_runner.py:99-191`; `controller/object_probe_coordinator.py:53-101`; `controller/pdf_controller.py:3315-3350`; `model/pdf_object_ops.py:1290-1300`; `src/render_worker/admission.py`; `src/render_worker/memory.py:110-120`; PyMuPDF `.venv/Lib/site-packages/pymupdf/table.py:1470-1490` (`cells_to_tables` drops every table whose box holds only whitespace) and `:2593-2700` (`find_tables`: rotation set to 0, small glyph heights, `get_layout`, `make_chars`).

**Design.**

1. *Admission, `src/render_worker/admission.py`.*
   - Add `OBJECT_PROBE_MEMORY_CEILING = 1728 * MIB` (comment: the measured peak commit of 1,341.5 MiB × 1.25, rounded up to 64 MiB; H24) and `OBJECT_PROBE_MIN_LIMIT = 256 * MIB`.
   - Add `object_probe_memory_limit(memory: SystemMemory | None) -> int | None`, which returns `None` when `memory` is `None`. Otherwise it returns `c = (min(OBJECT_PROBE_MEMORY_CEILING, memory.total_phys // 8, max(0, _headroom(memory)) // 2) // (64 * MIB)) * (64 * MIB)`, or `None` if `c < OBJECT_PROBE_MIN_LIMIT`.
   - Delete `OBJECT_PROBE_CHARGE` and its comment.
2. *Containment, `src/object_probe/memory_limit.py` (new, standard library and `ctypes` only).*
   - `class ContainmentError(RuntimeError)`.
   - `apply_job_memory_limit(limit_bytes: int) -> None`, on Windows:
     - Call `CreateJobObjectW(None, None)`, then `SetInformationJobObject` with `JobObjectExtendedLimitInformation` (class 9). Set `BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_PROCESS_MEMORY (0x100) | JOB_OBJECT_LIMIT_JOB_MEMORY (0x200)` and `ProcessMemoryLimit = JobMemoryLimit = limit_bytes`.
     - Then `AssignProcessToJobObject(job, GetCurrentProcess())`.
     - Then read the limits back with `QueryInformationJobObject` and require the flags and both limits to be equal.
     - Keep the job handle in a module global for the life of the process (never closed).
     - Any zero return or any mismatch raises `ContainmentError` with the `GetLastError` code.
   - On other platforms it raises `ContainmentError("unsupported platform")`. That is the outcome below, not a crash.
3. *Protocol v2 (amends H16).*
   - Request: `{"v":2,"kind":K,"sizes":[…],"mem":C}`, where `C` is an int in bytes.
   - Answer: `{"v":2,"status":S,…}` with `S` one of four values:
     - `"complete"`, which carries `"rects"`. An empty list is a real "no tables".
     - `"resource_limited"`.
     - `"analysis_failed"`.
     - `"containment_failed"`.
   - Only `complete` carries rectangles. `PROTOCOL_VERSION = 2` in the child and the runner; a v1 header is refused.
4. *Child, `src/object_probe/helper_main.py`.*
   - `_read_header(stream) -> tuple[str, list[int], int]`: `stream.readline(65536)`. A line with no newline, a bad JSON object, a missing or non-positive `"mem"` int, or a bad size raises `ValueError`.
   - `_read_payloads(stream, sizes) -> list[bytes]`: the payload loop of today.
   - `main()`, in this order:
     1. Read the header.
     2. `apply_job_memory_limit(mem)`; on `ContainmentError`, answer `containment_failed` and return 0 without reading the payloads or importing `fitz`.
     3. Read the payloads.
     4. Call the handler inside `try`:
        - `MemoryError` → `resource_limited`.
        - `table_objects.TableDetectionFailed` or any other `Exception` → `analysis_failed` (log the exception to stderr).
        - Success → `complete`.
   - A native crash still ends the process with no answer: the runner reports it as a failure (item 6).
5. *Model, `model/table_objects.py`.*
   - `class TableDetectionFailed(Exception)`.
   - `page_has_table_text(page) -> bool` repeats `find_tables`' own text step and nothing else, restoring every global it touched in `finally`:
     - `old_small = bool(fitz.TOOLS.set_small_glyph_heights())`, then `fitz.TOOLS.set_small_glyph_heights(True)`.
     - When `page.rotation != 0`, do `page_rotation_set0` / `page_rotation_reset` from `pymupdf.table` as `find_tables` does. The page is the scratch page, never the live one.
     - `page.get_layout()`. If `page.layout_information` is truthy, return `True`: the layout path is never short-cut.
     - Otherwise `tp = page.get_textpage(flags=pymupdf.table.FLAGS)` and return `not pymupdf.table.white_spaces.issuperset(tp.extractText())`.
   - `find_table_rects(page)`:
     - If `not page_has_table_text(page)`, return `[]`. This is exact: the library drops every table whose box holds only whitespace.
     - Then `finder = page.find_tables()`; `None` raises `TableDetectionFailed`.
     - The row, column and page-fraction filters are unchanged.
     - **No `try`:** exceptions propagate.
   - Failure memory:
     - `_failed_keys(model) -> set` on the model, next to `_cache`.
     - `mark_table_analysis_failed(model, key) -> None`, stored only if `key == frame_key(model, key[1])`. Stale keys are dropped by the same rule as `store_table_rects`.
     - `table_analysis_failed(model, page_num) -> bool`, true when the current `frame_key` is in the set.
     - `store_table_rects` removes its key from the failed set.
   - `table_rects` (blocking, for tests and scripts): on an exception it logs, stores **nothing** and returns `[]`.
6. *Runner, `controller/object_probe_runner.py`.*
   - In `_start_next`, `limit = object_probe_memory_limit(read_system_memory())`. If `limit is None`, start no process and emit `finished(job_id, {"v": 2, "status": "no_headroom"})`, then continue with the queue.
   - Otherwise the lease is `try_reserve("object-probe", "process", limit, required=True)`. The ledger only keeps accounts; the cap is the safety mechanism.
   - `_Job` gains `mem`, and `_started` writes it into the header.
   - `_parse` accepts only `v == 2` with a known `status`, and `"rects"` only when complete. Everything else stays as A3 (no answer or exit ≠ 0 → `failed`).
7. *Coordinator, `controller/object_probe_coordinator.py`.*
   - The signal becomes `probe_failed(str, int, str)` (kind, page, reason).
   - `_on_finished` by status:
     - `complete` → `store_table_rects` and `tables_ready` as today.
     - `resource_limited`, `analysis_failed`, `containment_failed` → no retry; `mark_table_analysis_failed`; `probe_failed(kind, page, status)`.
     - `no_headroom` → nothing stored or marked; `probe_failed(kind, page, "no_headroom")`.
     - A malformed `complete` → as runner `failed`.
   - `_retry_or_give_up`, for runner `failed` only: the first time, retry; the second time, `mark_table_analysis_failed` and `probe_failed(kind, page, "crashed")`. The line `store_table_rects(..., [])` is **removed**.
   - `request_tables` returns at once when `table_analysis_failed(model, page)`. A changed frame (edit, rotate) has a new key, so it tries again.
8. *Lookup, `model/pdf_object_ops.py` (non-blocking table step).* A miss returns `OBJECT_LOOKUP_PENDING` only when `not table_objects.table_analysis_failed(model, page_num)`. On a failed page the table step finds nothing and the lookup goes on to its next step, so a click is never pending forever.
9. *Controller, `_on_object_probe_failed(kind, page_num, reason)`.* It drops the pending click as today, and the status text depends on the reason:
   - `resource_limited` → 「此頁圖形過多，表格分析超出記憶體上限而未完成；此頁的表格目前無法選取或刪除（線條等其他物件不受影響）」
   - `no_headroom` → 「目前可用記憶體不足，暫時無法分析此頁的表格，請稍後再操作一次」
   - any other reason → 「此頁的物件分析失敗（第 n 頁）」 (as today)
   - `object_op_ready` for a `table` kind on a page where `table_analysis_failed` holds: return `False` with 「此頁的表格分析未完成，無法操作表格」 and request nothing.
10. *Docs.*
    - `docs/ARCHITECTURE.md`: the object-probe paragraph gets protocol v2, H24 and the outcome types.
    - `docs/PITFALLS.md` gets two entries, then regenerate the index:
      - "`find_tables` drops tables with no text, and `clip` does not bound its memory (`clean_graphics` calls a full-page `get_drawings`)".
      - "A Job Object memory limit makes allocations fail (`MemoryError` or a native exit 1); it does not kill the process".
    - `TODOS.md`: the six over-limit gestures, owned by A5.
    - `p19_probe_child_memory.py`: also report peak private commit, and rerun it with the preflight in place. Put the numbers in "Facts measured".

**Red first.**
- `test_scripts/test_table_text_preflight.py` (pure):
  - Fixtures from `test_table_objects._draw_table`: a normal page and a cropped page at rotations 0, 90 and 270, the page-sized grid, and a ruled table with no text. For each, `find_table_rects` equals the result with `page_has_table_text` patched to `True`. That is parity: the preflight never changes a result.
  - On the textless table, `fitz.Page.find_tables` patched to raise is never called. On a page with text it is called.
  - `find_tables` returning `None` raises `TableDetectionFailed`.
  - `table_rects` on a raising scratch page leaves `cached_table_rects` at `None`.
  - Small glyph heights, rotation and the MediaBox of the scratch page are restored.
- `test_scripts/test_object_probe_memory_limit.py`:
  - The formula table: 16 GiB total with 12 GiB free gives 1,728 MiB; 8 GiB total gives at most 1,024 MiB; 3 GiB total with 1.3 GiB free gives `None`; `None` in gives `None`; every result is a multiple of 64 MiB.
  - Windows-only, a subprocess run with `.venv` python: after `apply_job_memory_limit(128 MiB)`, allocating 256 MiB raises `MemoryError`, and the readback matches. With `SetInformationJobObject` patched to return 0, `ContainmentError` is raised.
- `test_scripts/test_object_probe_child.py`, extended:
  - The header is read before `apply_job_memory_limit`, and the payloads after it (a recording stream stub).
  - A containment failure answers `containment_failed` and calls no handler.
  - `MemoryError` in the handler answers `resource_limited`; `TableDetectionFailed` answers `analysis_failed`.
  - A v1 header is refused.
  - The real child, under `object_probe_memory_limit(read_system_memory())`, returns `complete` with the same rectangles as `table_rects` on a table fixture. On the sample (`needs_fixtures`) it returns `complete` with `[]`, and its time is recorded.
- `test_scripts/test_object_probe_runner.py`, extended: a `None` limit starts no process and emits `no_headroom`; the header's `mem` equals the lease bytes.
- `test_scripts/test_object_probe.py`, extended:
  - `complete` with `[]` is stored.
  - Each of `resource_limited`, `analysis_failed` and `containment_failed` gives no retry, nothing stored, the page marked, and the reason in `probe_failed`.
  - A runner failure gives one retry, then `crashed` and the page marked, never `[]` cached.
  - `no_headroom` does not mark the page, so the next request starts a job.
  - A marked page gives no new job on request, a lookup that is not pending, and `object_op_ready` refusing a table op with the message. After `rotate_pages` the page is probed again.
  - The three status texts.

**Accept:**
- Every test above, the A3 tests (`test_object_probe_runner`, `test_object_probe`, `test_object_probe_child`, `test_child_launch_guard`, `test_gui_stall` with `KNOWN_OVER_LIMIT` unchanged) and `test_table_objects`, `test_table_probe_non_mutation`, `test_object_click_on_vector_page` all pass.
- `ruff check .` is clean, and `mypy model/ utils/` is clean.
- The p19 numbers for the sample are in "Facts measured": peak commit with the preflight, expected under 100 MiB (Codex measured 61.1 MiB).
- The docs of item 10 are in place.

**Stop:**
- A parity case of the preflight differs on any fixture.
- `AssignProcessToJobObject` fails on this machine.
- The real child on the sample does not return `complete` under the computed limit.

Rejected from the advisory, recorded so they are not reopened: overlapping strips (they split a 4×3 table into two 2×3 tables and accept fragments of the page-sized grid); `clip` (it does not bound extraction); bounded transport buffering (the payload is the one-page scratch copy, 2.1 MB on the sample; not a memory risk next to the cap); `required=False` (the renderer ledger ceiling would refuse every budget).

### A4. Sonnet. Sample acceptance of M0
- **Do:** with the owner's sample in `test_files/cad_vector/before.pdf` (`needs_fixtures`): `test_scripts/test_cad_sample_click.py` runs, through the stall harness, a left click in 操作物件 and a right-click in browse, objects and text-edit modes.
- **Accept:** longest gap at most 100 ms on all four; the four numbers and the child's run time go into "Facts measured"; `TODOS.md` updated.

### A5. Sonnet. A path-heavy page that holds an image
On such a page discovery still tokenises the whole stream in-process (about 0.8 s per decoded MB), on every click and several times per edit. Design per H14, H15, H17, H18.

**Read:** `model/pdf_content_ops.py:23-155` and `:332-565`; `model/pdf_object_ops.py:298-415`, `:683-731`, `:806-877`, `:1008-1070`, `:2180-2440`.

**Design.**
1. *`model/content_scan.py` (new, standard library only).*
   - `iter_token_spans(stream) -> Iterator[tuple[int, int]]`: the loop of `tokenize_content_stream` moved here, yielding `(start, end)` for each token it appends today. `tokenize_content_stream` becomes `[ContentToken(stream[s:e]) for s, e in iter_token_spans(stream)]`. `_CONTENT_OPERATORS` moves here and is imported back.
   - `@dataclass(frozen=True) DoRecord`: `name` (no slash), `do_operator_index`, `do_span` (`[start of the Do's first operand token, end of the Do token)`), `cm_operator_index | None`, `cm_span | None` (`[start of that cm's first operand token, start of the cm token)`, the range `replace_operator_operands` replaces today), `cm_values | None` (as `_cm_values_from_operands`), `q_operator_index | None`, `q_end_operator_index | None`, `q_span | None` (`[start of the q's first operand token, end of the Q token)`; `None` when the `q` is never closed), `q_do_count` (every `Do` inside that `q`, nested ones included; 0 without a `q`).
   - `@dataclass(frozen=True) StreamScan`: `length`, `operator_count`, `dos: tuple[DoRecord, ...]` (every `Do`, whatever its name, in stream order).
   - `scan_stream(stream) -> StreamScan`: one pass over `iter_token_spans`, keeping only the operands since the last operator, a `q` stack and `last_cm_by_depth`; the rules are those of `discover_native_image_invocations` and `_q_bounds_by_operator_index` today, token for token. No token list is built.
   - `derive_after_replace(scan, start, end, new_len, new_cm_values) -> StreamScan` (a `cm_span` was replaced by `new_len` bytes): every offset at or after `end` moves by `new_len - (end - start)`; every record whose `cm_span` was `(start, end)` gets the new span and values; `length` follows; indices unchanged.
   - `derive_after_remove(scan, start, end, removed_operators, new_len) -> StreamScan` (bytes `[start, end)` replaced by `new_len` bytes): records whose `do_span` lies inside are dropped (call their number `k`); for the others, offsets at or after `end` move, operator indices greater than the removed range drop by `removed_operators`, and `q_do_count` drops by `k` when the record's `q_span` contained `[start, end)`.
   - Cache: module-level LRU `OrderedDict[bytes, StreamScan]`, at most 200,000 records in total; `content_key(stream) = blake2b(stream, digest_size=16).digest()`; `cached_scan(key)`, `store_scan(key, scan)`, `clear_scan_cache()`; plus an alias map from `(blake2b of the raw stream, the stream dictionary's text)` to the key, used only when that text contains no `\d+\s+\d+\s+R`. `to_json(scan)` and `from_json(obj)` for the child.
2. *`model/pdf_content_ops.py`.*
   - `INLINE_SCAN_LIMIT_BYTES = 131072`.
   - `stream_scan(doc, xref) -> StreamScan`: alias, else decode and key, else `scan_stream` and store. Always answers.
   - `discover_native_image_invocations`: both loops (page path and form path) read `stream_scan(doc, xref).dos` and keep their own placement logic; `NativeImageInvocation` gains `do_span`, `cm_span`, `q_span` (default `None`) and keeps every existing field with its meaning.
   - `image_scan_jobs(doc, page_num) -> list[tuple[bytes, bytes]]` (key, decoded stream): empty when the page has no image; else, for each stream the two loops would scan, the ones with no cached scan and a length over the limit.
3. *`model/pdf_object_ops.py`, splices (H17).*
   - `_image_cm_operator` is replaced by `_image_cm(doc, invocation) -> tuple[bytes, DoRecord] | None`: the stream and the fresh record whose `do_operator_index` matches; `None` when there is no `cm`. Its three users read `record.cm_values`.
   - Matrix rewrite: `new = stream[:a] + b" ".join(new_operands) + b" " + stream[b:]` with `(a, b) = cm_span`; `doc.update_stream(xref, new)`; then `store_scan(content_key(new), derive_after_replace(...))` with the values parsed from `new_operands`.
   - Delete: range = `do_span`; it becomes `q_span` when `q_span` is set, `q_do_count == 1`, `q_span` is at most 65,536 bytes long and `_q_block_paints_only_the_do` holds on `parse_operators(stream[q_start:q_end])` (index of the `Do` found by name and position in that window). `new = stream[:a] + b"\n" + stream[b:]`; `removed_operators` is 1, or the window's operator count; store the derived scan. The resource pruning that follows is unchanged.
   - `_invocation_slot` is unchanged (operator indices are still stable under a matrix rewrite).
   - `get_object_info_at_point(..., blocking=False)` returns `OBJECT_LOOKUP_PENDING` before the native-image step when `image_scan_jobs` is non-empty. `PDFModel.image_scan_jobs(page_num)` delegates.
4. *Child and coordinator.* Kind `scan`: payloads are the decoded streams; the child answers `to_json(scan_stream(p))` for each. `ObjectProbeCoordinator.request_image_scan(page_num)`: job key = the tuple of content keys; submitted through the same runner; on success `store_scan` for each and emit `image_scan_ready(int)`; failure as in A3, with the keys remembered in `failed_scan_keys` so that `image_scan_jobs` skips them and the page then reports no native image.
5. *Controller.* `lookup_object_at_point` requests the scan when the model reports jobs (status 「正在背景分析此頁的影像，完成後會自動選取…」); `image_scan_ready` resolves the pending click like `tables_ready`. `object_op_ready` also returns `False`, requests the scan and shows 「正在分析此頁的影像（此頁內容較多），完成後請再操作一次」 when a kind is `native_image` or `image` and `model.image_scan_jobs(page)` is non-empty for a source or destination page; `image_scan_ready` then shows 「此頁影像分析完成，可以操作了」 for 4 s. `move_object`, `resize_object`, `rotate_object` call `object_op_ready` first and on `False` call `_tell_view_object_op_refused(ids)` and return; `add_image_object` returns after the message; `delete_object` as in A3. Batches check every member before any is executed.

**Red first.** `test_scripts/test_content_scan.py`: for every content stream and image-bearing form stream of the fixture pages that have images, and for synthetic streams (nested `q`, several `Do` under one `cm`, a `Do` without `cm`, an unclosed `q`, strings and comments holding `Do`), `scan_stream` equals a reference built in the test from `parse_operators` and a copy of today's loop; `tokenize_content_stream` output is unchanged; each `derive_*` result equals `scan_stream` of the new bytes after every move, resize, rotate and delete in the existing object tests' scenarios; the alias is not used when the dictionary holds a reference. `test_scripts/test_native_image_ops_stall.py` (Qt): on a 200,000-path page with one image: click, move, resize, rotate, delete and undo of each; `parse_operators` patched to raise on inputs over 65,536 bytes is never reached.

**Accept:** existing object tests pass unchanged; the stall test gives at most 100 ms for the click and at most Q1 for each edit and undo; the cold-edit refusal and the "ready" message are tested with the stub child.

**Decision rule for the limit:** if the click on an ordinary fixture page (stream under the limit, cache cold) exceeds 100 ms in the stall harness, halve `INLINE_SCAN_LIMIT_BYTES` and rerun, down to 16,384; below that, stop.

**Stop:** if an existing test asserts the whole re-serialised stream after a native-image edit (report the test; do not change it); if decoding plus hashing the streams of the stall fixture exceeds 100 ms on the click path.

## Track B: M1, select and delete

The rules (what a path is, which flags, which bytes are cut, the gate, the copy rule, the oracles) are in the design plan, sections 3 to 9; cards cite them. What is fixed below is the code shape. Design plan step numbers are in brackets.

### Shared shapes (all of Track B)
- **Package `model/vector_paths/`** (imported lazily; numpy imported inside it): `scan.py`, `index.py`, `edit.py`, `commit_state.py`, `__init__.py` re-exporting the names below.
- **`scan.py`.** `Frame = tuple[float, float, float, float, float, float]` (`page_user_space_matrix`). `class PathFlag(enum.IntFlag)`: `EDITABLE, DEGENERATE, SETS_CLIP, CLIPPED, IMPURE, SPANS_STREAMS, IN_OC, CTM_SINGULAR, PAGE_ANCHORED`. `class VectorPageRefused(Exception)` with `code` (`"NO_FRAME" | "TOO_LARGE" | "SCAN_ERROR" | "CHORD_CAP"`) and `detail`. `@dataclass VectorIndex`: `paths`, `cubics`, `segments`, `blocks`, `streams` (numpy structured arrays with the columns of §4.1), `indexed_end: int`, `stopped_at_inline_image: bool`, `frame: Frame`, `stream_digests: tuple[bytes, ...]` (SHA-256 of each decoded stream), `nbytes: int`. `scan_page(streams: Sequence[bytes], frame: Frame, *, cancel: Callable[[], bool] | None = None, progress: Callable[[int, int], None] | None = None, accelerated: bool = False) -> VectorIndex`. Caps: 256 MiB decoded, 4,000,000 paints, 8,000,000 chord rows.
- **`index.py`.** `select(index, rect: tuple[float, float, float, float], tolerance: float, mode: Literal["click", "touch", "contain"]) -> numpy.ndarray` (bool mask over paths; `rect` in unrotated page space; non-editable rows are never set); `combine(old, new, how: Literal["replace", "add", "toggle"])`; `summary(index, mask) -> tuple[int, int, tuple[float, float, float, float] | None]` (selected, skipped, bbox); `selected_segments(index, mask) -> numpy.ndarray` (float32 `(K, 4)`, unrotated).
- **`edit.py`.** `@dataclass VectorPlan`: `kind: Literal["delete", "move"]`, `frame`, `source_digests`, `ranges: tuple[numpy.ndarray, ...]` (per stream, `(R, 2)` int64), `new_streams: tuple[bytes | None, ...]` (`None` = untouched), `new_compressed: tuple[bytes | None, ...]` (`zlib.compress(level=6)`), `planned_digests`, `derived: VectorIndex`. `plan_delete(index, mask, streams, *, cancel=None) -> VectorPlan`.
- **`commit_state.py`** (the only module of the package that reads a document): `vector_page_prestate(doc, page) -> PagePrestate`; `reference_counts(snapshot: bytes, xrefs: Iterable[int]) -> dict[int, int]` (D20b's rule); `digest_table(doc, *, on_yield: Callable[[int, int], None] | None = None, yield_every_ms: int = 50) -> DigestTable` (H8; with `on_yield` it runs in slices, H22; `DigestTable.elapsed_ms` is the work time without the yields); `@dataclass WriteSet`: `page_xref`, `stream_xrefs: frozenset[int]`, `new_xrefs: frozenset[int]`; `undeclared(before, after, write_set) -> list[int]`.
- **`model/pdf_model.py` delegators.** `vector_page_source(page_num) -> tuple[tuple[bytes, ...], Frame]`; `install_vector_index(page_num, index)`; `vector_index(page_num) -> VectorIndex | None` (LRU of §4.1, 256 MB); `vector_select(query) -> VectorSelectionInfo`; `vector_selection_segments() -> numpy.ndarray` (visual coordinates); `vector_plan_inputs(token) -> tuple[VectorIndex, numpy.ndarray, tuple[bytes, ...]]`; `commit_vector_plan(plan, token, *, on_yield=None) -> VectorCommitResult | None` (`before_bytes`, `digest_before`, `digest_after`; `None` after a refusal recorded through `_refuse`; `on_yield` is used only when `vector_last_pass_ms > 400`, H22); `vector_last_pass_ms: float` (set by every pass); `verify_vector_digest(table) -> bool`; `vector_editing_blocked: str | None` (the sentence, once latched).
- **Requests** in `model/object_requests.py` as in §7.2, with `VectorSelectionQuery.mode` one of `"click" | "touch" | "contain" | "all" | "clear"` and `combine` one of `"replace" | "add" | "toggle"`. **Refusals** in `model/object_op_refusal.py`: `VECTOR_PAGE_UNSUPPORTED`, `VECTOR_SELECTION_STALE`, `VECTOR_NOTHING_EDITABLE`, `VECTOR_COMMIT_REJECTED`; sentences in `controller/object_op_refusals.py` as quoted in the design plan.

### B1. Sonnet [Step 2]. Twins, builder, oracles, calibration
- **Files:** `test_scripts/vector_fixture_builder.py` (scene model: `Scene(pages)`, `PathSpec(kind, points, paint, ctm, state)`, `Topology` options of §9; `build(scene) -> bytes`; `expected(scene, op) -> tuple[bytes, Facts]`; `mutants(scene, op) -> list[tuple[str, bytes, Facts]]`), `test_scripts/vector_oracles.py` (one function per oracle of §9, each `oracle(op, before, after, **kw) -> list[str]` returning violations and raising on an operation it has no rule for; each with a `DOMAIN` frozenset of fact kinds), `test_scripts/vector_matching.py` (H7), and `model/vector_paths/commit_state.py` with `digest_table` and `undeclared` only.
- **`Facts`** (fixed list of kinds): `PATHS` (ordered list of `(paint, primitives in page space, stroke colour, fill colour, width, dashes)`), `OTHER_PAGES` (per page, the same list), `OUTSIDE_BYTES` (digest of the decoded stream with the legal envelopes removed), `OBJECTS` (per object key, digest; plus the set allowed to change), `PIXELS_OUTSIDE` (render digest outside the changed region), `DICT` (`vector_page_prestate` normal form).
- **Oracle domains** (fixed): O-rebuild: all; O-struct: `PATHS`; O-pixel: `PIXELS_OUTSIDE`; O-bytes: `OUTSIDE_BYTES`; O-dict: `DICT`; rule B: `OBJECTS`, `OTHER_PAGES`.
- **Mutants** (fixed list; each defined on the scene): neighbour deleted too; one selected path kept; block removed where a D17 rule fails; range shifted by one token; write in place on a shared stream; copy skipped with a shared indirect array; `/Rotate` changed on the edited page; a trailer key changed; a foreign stream changed; restore skipped after a failure; `/Contents` left repointed after a rollback; extra dictionary key; decoded bytes restored under another filter. Move mutants are added in C1.
- **Red first:** `test_vector_fixture_builder.py` (fails on import), then `test_vector_oracle_calibration.py`.
- **Accept:** every oracle has at least one must-kill cell and rejects all of them and accepts every must-pass input; a deliberately blind oracle fails the run; a mutant outside every domain fails the run; the matcher pairs two records that a greedy pass would mispair; the D24 guard test (`test_gate_provenance.py`, H12) exists and fails on an empty cell.
- **Stop:** if a mutant in the fixed list turns out equivalent on every topology (report it; do not delete it).

### B2. Sonnet [Step 3, scanner G]
- `scan_page(..., accelerated=False)`: the plain reference. One compiled alternation for strings, hex strings, dictionaries, comments, brackets, names, words; a Python loop for `q`/`Q`/CTM (`affine_concat`), flags (H11) and rows. Text objects are lexed, only their strings skipped. Every inline image stops the scan at its `BI` (H13). Cubic chords by the formula of §4.1, ε = 0.01 pt.
- **Red first:** `test_vector_scan.py`, every fixture listed under Step 3 of the design plan including its "Review additions", "Revision 10" (except the F and proved-image lines) and "Revision 11" lines.
- **Accept:** O-scan on every twin and rotation; the test file green; linear-time guard green.

### B3. Sonnet. Measure G through the product path, then apply the rule
- **Do:** `controller/vector_edit_coordinator.py` with only the index worker (shape in B7) and `plans/cad-vector-object-editing-probes/p20_scan_gate.py`, which enters through `PDFModel.vector_page_source` and the worker, three runs on the sample, and records wall time, peak memory above baseline and the heartbeat gap (H5 harness) with their callables (H12).
- **Decision rule (apply, do not judge):**
  1. median ≤ 4.0 s, gap ≤ 100 ms, memory ≤ 400 MB → ship G; skip B4.
  2. gap > 100 ms (whatever the time) → apply H21 (scan in the child) and measure again; then rule 1 or 3.
  3. median > 4.0 s or memory > 400 MB → B4.
- **Accept:** the three numbers and the rule that applied are written into "Facts measured".

### B4. Sonnet [Step 3, accelerator F]. Only if B3 rule 3 applied
- `scan_page(..., accelerated=True)`: the four stages of §4.2 "F after S0", H10, H11, a `ThreadPoolExecutor(max_workers=min(4, os.cpu_count() or 1))` created and joined inside the call, tokenising in 4 MB chunks cut at whitespace, stage 3 and stage 4 in batches of 65,536 structural operators and 65,536 paths. Any stream F does not admit (unterminated span, `Q` below depth 0) is handed to G inside the same call.
- **Red first:** the F lines of Step 3 (F equals G on every twin, on 500 fuzzed streams with fixed seeds, on the name, dictionary and number fixtures).
- **Accept:** F equals G (array equality, every column) on twins, fuzz and the sample; rerun `p20_scan_gate.py` with `accelerated=True`.
- **Decision rule:** median ≤ 4.0 s, gap ≤ 100 ms, memory ≤ 400 MB → ship F for pages over 1 MB decoded and G below. F differs from G on a real file after two fix attempts → ship G with the progress line, record the file, tell the owner. F equal but over a limit → stop and report the three numbers.

### B5. Sonnet [Step 4]. Queries
- `index.py` as in "Shared shapes". Click: box prefilter grown by the tolerance, then point-to-segment distance, topmost (largest row) wins; a fill also hits when the point is inside (even-odd or non-zero per its paint operator). Touch: rows whose box lies inside the rectangle are taken; rows whose box straddles an edge get the segment test (Liang–Barsky per segment, vectorised). Contain: box inside.
- **Red first:** `test_vector_index_queries.py`, the fixtures of Step 4 with its additions.
- **Accept:** the fast path equals the plain segment test on every twin and on 200 random rectangles; O-flat; at most 50 ms per query on the sample (product path: `PDFModel.vector_select`).

### B6. Sonnet [Step 5, 6]. Delete plan, commit, undo
- **`plan_delete`:** D7 and D17 exactly; adjacent ranges merged; `derived` built by dropping rows and shifting offsets.
- **`commit_vector_plan`, in this order, on the GUI thread:** (1) token check (H20) and `vector_editing_blocked`; (2) gate of §4.3, items 1 to 4; (3) `before = _capture_doc_snapshot()`, prestate, copies of `pending_edits`, `edit_count`, `secure_save_required`; (4) `T0 = digest_table(doc)`; (5) per edited stream: exclusive by D20b's chain on `before` (`reference_counts`) and no indirect reference in its dictionary → in place; else a new object: `xref = doc.get_new_xref()`, dictionary written with direct values first (`/Filter /FlateDecode`, no `/DecodeParms`, no `/DL`, other keys copied), then the page's `/Contents` written as a direct array; (6) `WriteSet` declared; (7) `update_stream(xref, compressed, compress=False)` then the `/Filter` keys; (8) post-check of §5.3; (9) `T1 = digest_table(doc)`; `undeclared(T0, T1, write_set)` must be empty and each new xref has exactly one reference; (10) success bookkeeping of §5.3 and D19; return the result. Any exception or failed check after step 3: the single failure path of §5.3, then `digest_table(doc)` must equal `T0`, else latch `vector_editing_blocked = "此文件在還原後與原狀不一致，本次工作階段已停用向量編輯"`. A rejected commit (step 9) shows 「編輯已取消：文件的其他部分發生了預期外的變更」.
- **Undo:** the controller records `SnapshotCommand(command_type="vector_delete", …)` and sets two attributes on it, `vector_digest_before` and `vector_digest_after`. After an undo or redo of a command that has them, the controller calls `model.verify_vector_digest(...)` with the matching table; `False` latches as above.
- **Slow documents (H22):** steps 4 and 9 pass `on_yield` when `vector_last_pass_ms > 400`, with the `(model.handle_generation, model.content_revision)` guard around each (H3 as amended 2026-11-19; never `id(doc)` or `edit_count`). The controller's callback is the only place that calls `processEvents`. Before coding, have `Explore` list every `QTimer`, queued signal and worker result handler that writes or serialises `model.doc`; put the list in this card.
- **Eligibility (H9), run by the coordinator on first entry of the mode per document revision:** live `digest_table` with `on_yield` (always sliced here); `serialize_document_bytes`; a second live pass; the snapshot goes to the child through `ObjectProbeRunner` (kind `digest`: `fitz.open(stream=…)`, `digest_table`, answer as hex). Pass = the first table equals the second and equals the child's. Otherwise 「此文件的結構在存檔後會改變，無法進行向量編輯」 and `VECTOR_PAGE_UNSUPPORTED`. When the measured pass is over 400 ms, the notice of H22 is shown once.
- **Red first:** `test_vector_delete_model.py` and `test_vector_delete_undo_save.py`, the fixtures of Steps 5 and 6 with their additions; plus: an injected foreign write after step 7 is rolled back with the message; an undo whose table differs latches; P17's `cycle` through `commit_vector_plan`.
- **Red for H22:** with `digest_table` slowed by a stub so that a pass takes 600 ms, a commit completes with a longest heartbeat gap of at most 1 s and the progress line shown; a timer that bumps `edit_count` during T0 gives a stale refusal with no byte changed; the same during T1 latches with the sentence of H22 and keeps both changes.
- **Accept:** O-rebuild, O-struct, O-pixel, O-bytes, O-dict and rule B on every twin; the fault matrix; commit and undo stall on the sample at most 1 s (H5 harness); then the Codex round of H23.
- **Stop:** if the list of timer- or signal-driven writers is not empty (report it with the call chains); if `update_stream` writes `/Length` through an indirect reference (probe P16 is the first red test of this card); if the secure save rewrites streams (class A of D16 then holds for moves only: report).

### B7. Sonnet [Step 7, 8]. Coordinator and view
- **`controller/vector_edit_coordinator.py`**, `class VectorEditCoordinator(QObject)` (the `SearchCoordinator` shape; no self-deleting worker, no lambda capturing `self` on a child thread): `_IndexWorker(QThread)` (`run`: `scan_page`; signals `progress(int, int)`, `done(object, int)` with the generation, `refused(str, int)`), `_PlanWorker(QThread)` (`plan_delete`; `done(object, int)`). Methods: `enter_mode(page_num)`, `leave_mode()`, `ensure_index(page_num)`, `query(VectorSelectionQuery)`, `delete(DeleteVectorSelectionRequest)`, `cancel()`, `drop_selection()`. A generation counter is bumped by `drop_selection`, by a change of `(session_id, render_revision)` and by `cancel`; a result with an older generation is discarded. `drop_selection` is called from the chokepoints that clear the object selection today (§8 "Selection lifetime").
- **Controller wiring** in `PDFController.activate()`: `view.sig_vector_query`, `sig_vector_delete`, `sig_vector_cancel` → coordinator; coordinator → `view.vector_selection.set_selection(info, segments)`, `set_progress(text | None, percent)`, refusals through `_show_object_refusal`. After a successful commit: `SnapshotCommand`, `_invalidate_active_render_state()`, `show_page`, `_update_undo_redo_tooltips()`.
- **View:** `view/vector_selection.py` with `VectorSelectionManager` (holding `self._view`, like `ObjectSelectionManager`) and `VectorSelectionOverlayItem(QGraphicsItem)` (one per page; cosmetic pen; above 200,000 visible segments it paints from a cached `QImage` filled with numpy). Mode `"vector"` 「編輯向量物件」 through `_make_mode_action`; cross cursor; press and release within 3 px = click query (`tolerance = 3 / render scale`), a larger drag = marquee (Alt = contain, Shift = add, Shift+click = toggle); Delete and Backspace, and a context menu with 「刪除」, 「全選此頁向量物件」, 「取消選取」. Progress in the status bar: 「正在分析此頁向量物件… n %」 with Esc to cancel. `pyproject.toml`: `"view.vector_selection -> model.object_requests"`.
- **Red first:** `test_vector_edit_coordinator.py`, `test_vector_selection_gui.py` (Steps 7 and 8).
- **Accept:** those tests; the stall harness on mode entry, marquee, delete and undo on the twins.

### B8. Sonnet [Step 9]. Sample acceptance
`test_vector_cad_sample_acceptance.py` (`needs_fixtures`): O-scan, O-struct, O-pixel, O-reopen, O-vendor; gates B0 to B6 through the product path with H12. Numbers into "Facts measured". Then the `/verify` run of §9. **Stop and report** to the owner.

## Track C: M2, move

- **C1. Sonnet [Step 10].** `edit.py::plan_move(index, mask, streams, delta_user: tuple[float, float], *, cancel=None) -> VectorPlan`. Per selected path: refuse the whole plan with `VECTOR_NOTHING_EDITABLE` if any selected row is `CLIPPED` or `PAGE_ANCHORED` (D21); D8a when its leaf block passes D17's four rules, holds exactly one `cm` and that `cm` precedes the first construction operator; otherwise D8b. Numbers per H19. `commit_vector_plan` is reused unchanged (a move does not latch `secure_save_required`). Builder: move mutants (delta without the inverse CTM; D8a applied where a rule fails; an anchored path moved; a second move nesting a wrapper) and product-shaped must-pass inputs. Red: `test_vector_move_model.py`.
- **C2. Sonnet [Step 11].** Press on the selection and drag translates the overlay item with no model call; release emits `MoveVectorSelectionRequest`; Esc cancels; a refusal snaps back. `_PlanWorker` runs `plan_move`. Red: `test_vector_move_gui.py`.
- **C3. Sonnet [Step 12].** Sample acceptance for move with save and reopen; numbers here; report to the owner.

## Facts measured on 2026-11-17 that the cards rely on

- Sample page: 0 images; `find_tables` alone 12.6 s, 0 tables; one-page scratch copy plus bytes 8 ms and 2.1 MB.
- `insert_pdf` source mutation: see H1.
- Digest pass (first form, no page split or trailer): 133 to 215 ms on 36 to 47 MB files; no-edit save and reopen keeps every object on 98.5% of `test_files/` with the product's save prelude (library fact: called `tobytes`, not `serialize_document_bytes`).
- Scanner prototypes (lower bounds, not gates): masked F 2.3 to 2.5 s on the sample at 4 workers; marquee 11 to 14 ms; click 19 ms.
- A3b, `p19_probe_child_memory.py` under the H24 cap with the text preflight (2026-11-18, this machine): sample page 1 answers `complete` with `[]`, peak working set 55.0 MiB, peak commit 59.2 MiB, child run time 0.6 s; stall fixtures (form / paths / images): peak commit 51.0 / 51.0 / 133.7 MiB, all `complete`, 0.2 s each.
- A4, `test_cad_sample_click.py` on the sample, page 1 centre (2026-11-18, this machine): longest gap left click in objects 31.8 ms, right click in browse 1436.5 ms (OVER the 100 ms limit), right click in objects 18.6 ms, right click in text edit 20.6 ms; time from gesture to settled table analysis 862 / 1657 / 828 / 844 ms. Accept NOT met on browse. Cause (cProfile): the browse text hit, `get_text_info_at_point` → `content_textpage`, runs `fz_run_page_contents` 3 times at about 400 ms each, plus a first `ensure_page_index_built` of about 800 ms; the warm repeat is 406 ms.
- `rotate_pages` does not change `edit_count` (Codex, read in code, not run).
- Read in code by Fable, not run: native-image edits re-serialise the whole stream through `serialize_tokens`; every discovery chain starts in one of `move_object`, `resize_object`, `rotate_object`, `delete_object`, `add_image_object` or the point lookup; `_invocation_slot` is `(stream xref, Do operator index, image xref)`.

## Kickoff: how a session starts work

1. **Session shape.** Opus is the main session in Claude Code at the repository root. It reads this file's top block, then gives **one card at a time** to the `implementer` subagent (Sonnet) with the prompt below. It does not paraphrase the card.
2. **Prompt for the implementer (fill in the card id):**
   > Implement card **<ID>** of `plans/cad-vector-object-editing-handoff.md`. Read the top block, the "Decisions fixed here" entries the card names, and the card. You may read `plans/cad-vector-object-editing.md` for the rules the card cites; where the two differ, the handoff file wins. Write the red tests first and show them failing, then the code. Run one pytest at a time with `.venv\Scripts\python.exe -m pytest <file>`. Do not design: if anything is not fixed by the card, or a test contradicts the card, stop and report the exact question with file and line. Do not commit. Finish with: files changed, tests added and their results, numbers the card asks for, and anything you could not do.
3. **After each card, Opus checks** the card's "Accept" lines one by one against the implementer's output (rerunning the named tests itself), runs `ruff check .`, and writes one line into the running log: card, date, result, numbers. A "Stop" goes to the owner word for word.
4. **Commits** only when the owner asks; suggested unit: one card, one commit.
5. **Reviews** at the four points of H23.
6. **Ready now:** A1 and A2 need nothing else. A3 needs A2's functions. A4 needs the owner's sample copied to `test_files/cad_vector/before.pdf` (gitignored; the owner does this). A5 needs A3's runner. Track B needs numpy (already a dependency) and, for B8, `test_files/cad_vector/after_vendor.pdf`.

## Running log

- **2026-11-17.** Written by Fable at the owner's request so that the work does not depend on Fable.
- **2026-11-17, second edition.** The owner agreed to the M0 cut and ruled that Sonnet must not design. Every "Opus design note" and "Opus decides" was replaced by a written design or a mechanical decision rule: A3 (child, protocol, coordinator, pending click), A5 (content-keyed scan, byte splices, derived scans, refuse-and-wait for cold edits), B1 to B8 (module shapes, commit order, fixed fact and mutant lists, B3's rule), C1 to C3. New decisions H14 to H21. None of this edition has been reviewed or run.
- **2026-11-17, evening.** Owner: commit stall limit 1 s; the time of the integrity check must not refuse a document and megabytes are not a criterion (H22 replaces the 400 ms refusal); Codex reviews and Opus adjudicates (H23). A3's process handling was split into an App-wide runner and a per-controller coordinator after reading the service loop in `main.py`. "Kickoff" section added.
- **2026-11-17, A1 ACCEPTED.** The early return only, plus `test_scripts/test_object_click_on_vector_page.py` (3 pass). It was red first: the old code raised on the 20,000-path page. Old and new discovery agree on all fields on 66 fixture pages. Opus then tightened both "unchanged" tests to compare every field. The 21 object and image test files pass and ruff is clean.
- **2026-11-17, A2 ACCEPTED.** `frame_key`, `scratch_page_bytes`, `find_table_rects`, `cached_table_rects` and `store_table_rects` were added. `test_table_probe_non_mutation.py` (10 tests) failed 7 before the change: object 85 changed on the text-annotation page. All 10 pass now, and `test_table_objects` (11) passes too, so no fixture lost a table. The PITFALLS entry and the regenerated index are in.
  - Other scratch copies, checked with the digest: `tools/manager.py:276` changes object 85 on the text-annotation page; `:311` changes it on every page. `text_paint_state.py:932` and `watermark_raster.py:71` are safe, read in code only. Fixing these is a separate task.
  - **Owner to confirm:** item 4 says "first four key fields". The code keeps today's eviction instead, which drops an entry only when `id(doc)` or `edit_count` differs.
- **2026-11-17, A3 STOPPED (code in the tree, not accepted).** Two Stop or Accept lines failed; they went to the owner word for word.
  - (1) p19 measured the child's peak at 1,335.5 MiB on the sample page. The rule therefore gives 1,344 MiB, which is over the 1,024 MiB stop line. The constant is set to that value and marked pending.
  - (2) The 100 ms limit fails in six cases:
    - Browse right-click on the form and path fixtures: 205 to 214 ms. About 120 ms of that is the one-time `ensure_page_index_built`.
    - All four gestures on the three-image fixture: 256 to 457 ms. About 140 ms is the MD5 of each image in `get_image_rects` (A5's ground), and `scratch_page_bytes` takes 84.5 ms.
    - The six cases are pinned as `KNOWN_OVER_LIMIT` in `test_gui_stall.py`.
  - The other gestures take 18 to 23 ms; before the change the path-page click took 7,817 ms.
  - Child run times: form 8.6 s, paths 8.4 s, images 0.2 s, sample 13.8 s.
  - The implementer added things the card does not name, for the owner to confirm:
    - `ObjectProbeRunner.is_waiting`.
    - The coordinator's `runner=` injection argument.
    - A view fallback to `get_object_info_at_point` for test doubles.
    - A pending press is not swallowed in text-edit mode.
    - The child sends Python stdout to stderr, because PyMuPDF prints an advisory line after the answer.
- **2026-11-18, owner rulings on A3, and card A3b.** A1 and A2 are committed.
  - The owner approved H24's cap formula and its ratios.
  - The six slow gestures go to A5.
  - The owner confirmed that the no-text preflight is acceptable: "table" means a `find_tables` grid, not line editing.
  - Opus wrote A3b from the Codex advisory (gpt-6-astra high, read-only, measured). The advisory's strip and clip options are rejected, with the reasons in A3b. A3b waits for the owner's go before it goes to the implementer.
- **2026-11-18, A3b.** First run stopped on the card's own Stop line "an existing test asserts that a failed probe caches `[]`" (the uncommitted A3 test `test_object_probe.py:195-210`). The owner removed that line and ruled that the A3 tests are amended by A3b.
  - Second run: every test file passes: preflight 17, memory limit 14, child v2 14, child 4, runner 23, probe 51, table objects 11, non-mutation 10, vector-page click 3, launch guard 18, gui stall 3 with `KNOWN_OVER_LIMIT` unchanged. Ruff and mypy are clean. p19 numbers are in "Facts measured". `/verify` on the sample: a click in 操作物件 had a longest gap of 18.8 ms and finished.
  - Opus added the missing `cropped_rot270` parity case.
  - **Stop (waiting for the owner).** The card's literal preflight breaks parity on cropped pages at 90 and 270: `pymupdf.table.page_rotation_reset` does not put back the CropBox that `set_mediabox` wipes. The implementer added `page.set_cropbox(...)` after the reset (`model/table_objects.py`, `page_has_table_text`). With it, parity holds at 0, 90, 180 and 270, cropped and uncropped.
  - **Beyond the card (waiting for the owner).** `ObjectProbeCoordinator` holds an answer that the runner emits synchronously inside `submit()` (no_headroom, ledger refusal, refused start) and delivers it once the job id is registered. Without it a `no_headroom` answer is dropped.
  - Also: the new child tests are in `test_object_probe_child_v2.py` instead of extending `test_object_probe_child.py`.
  - **Code review (`plan-code-reviewer`, Opus) on the A3 and A3b diff: verdict fix-first.** All 11 files, ruff and mypy pass. Both additions checked out: the CropBox restore holds on 16 combinations (rotation × MediaBox origin × CropBox), and the early-answer buffer is correct. Open for the owner, none fixed, because each changes a fixed decision:
    - **B1.** `resource_limited` cannot be reached when memory runs out inside `find_tables`. `pymupdf/table.py:2720-2722` catches every `Exception`, and MuPDF's native errors are not `MemoryError`. The answer is `analysis_failed` with the "analysis failed" message instead. A3b item 4's mapping rests on a wrong library assumption. PITFALLS now says so.
    - **B2.** `id(doc)` is reused after `close_session` (9 of 20 cycles). The A3b failed set, and the table cache committed in A2 and earlier, leak onto the next document. Proven destructive: after closing doc A (one table), a non-blocking click on doc B returned a `table`, and `delete_objects_atomic` erased B's text. The fix is at class level: drop `_CACHES`/`_FAILED` on session open or close, or key on a token that is never reused. This changes H3.
    - **N1.** Zoom drops a pending click: `change_scale` → `_clear_object_selection` → `bump_object_click_generation`. This contradicts H4 "scroll and zoom do not cancel it"; the code follows A3 item 5 literally.
    - **N2.** In a batch delete, the first delete bumps `edit_count`, so the second table runs `find_tables` on the GUI thread (`controller/pdf_controller.py:3515`). This breaks H14/H15 for multi-select.
    - **N3.** Off Windows, `read_system_memory()` is `None`, so every job is `no_headroom`. Table select and delete never work there, and the message says to try later.
    - Minor: with an older selection, the context menu still shows "Delete Object" under the disabled "analysing" entry (`view/pdf_view.py:6381-6390`).
  - Per the owner's overnight instruction ("on a Stop, skip the stopped item and finish the rest"), both additions are committed with A3 as they are, and the review findings above wait for the owner. To revert the CropBox restore, remove those lines; the parity test then fails on `cropped_rot90` and `cropped_rot270`.
- **2026-11-18, A4: Stop (rule 1), committed `a441a844` with the gesture recorded as known.** `test_cad_sample_click.py` on the sample:
  - Longest gaps: left click in objects 25 to 32 ms; right click in browse 1,346 to 1,437 ms; right click in objects 19 to 22 ms; right click in text edit 18 to 23 ms.
  - Cause (Opus, cProfile): the browse right-click does a text hit on the GUI thread. `get_text_info_at_point` → `page_content_text.content_textpage` runs `fz_run_page_contents` over the whole CAD page 3 times at about 400 ms each, plus a first `ensure_page_index_built` of about 800 ms. A warm repeat still takes 406 ms. No card covers this: it is neither table nor image work. It is the same class as the `_TEXT_INDEX` entries in `test_gui_stall.py`, much larger on the sample.
  - The test holds it in `KNOWN_OVER_LIMIT` (strict both ways), the same pattern the owner approved for A3.
  - Owner to rule: a card for the text hit (off the GUI thread, or one `content_textpage` per page instead of three), or accept it.
- **2026-11-18, A5: Stop, NOT committed (the code is in the tree).** The 7-day quota breaker (96 %) blocked the code review, and CLAUDE.md requires one before "done" on a diff of this size.
  - Built: `model/content_scan.py` (scan, derive, LRU cache, alias), byte splices for the native-image matrix and delete (H17), child kind `scan`, `request_image_scan`/`image_scan_ready`, and cold-page refusal for every image edit.
  - Tests: content_scan 58, native_image_probe 32, native_image_ops_stall 1, runner 24, and every `*object*` test file passes.
  - Opus fixed two guard regressions that `test_exact_object_text.py` caught; that file now passes 187:
    - `set_cropbox` in `page_has_table_text`, from A3b (`2be2e3b1`), now runs inside `exact_set_key`.
    - `_stream_dict_text` now uses `xref_object_exact`.
  - **Accept not met. Each needs an owner ruling; no design was chosen:**
    1. The six `test_gui_stall` gestures are not fixed. Four are on the images fixture: `page.get_image_rects` MD5-hashes 3 × 16 MB pixmaps (313 to 380 ms), and A5 keeps `get_image_rects`. The halving rule for `INLINE_SCAN_LIMIT_BYTES` cannot help: that stream is tiny. The other two (form/paths, browse) are text-index work, outside A5.
    2. Edits on the 200,000-path image page: move, resize, rotate and delete take 1,082 to 1,241 ms, over Q1 (1 s). About 0.59 s of that is `doc.update_stream` deflating the 4.3 MB stream. Question: may the splice use `compress=0` or a lower level? That changes file size. Undos take 375 to 433 ms.
    3. The click on that page is 115 to 119 ms: the answered click reruns discovery, and `get_image_rects` takes about 57 ms. Same question as item 1.
    4. Wording for a scan job that ends `resource_limited`: it currently reuses the table message.
  - Implementer's judgement calls, for the owner to confirm:
    - A single scan over the 200,000-record cap is stored alone.
    - `derive_after_remove` raises `ValueError` when the range holds no `Do`.
    - The failed scan keys live in `content_scan` (`mark_scan_failed`/`scan_failed`), not in the coordinator's `failed_scan_keys`.
    - The runner's `_parse` now accepts `scans`; without that, every scan answer was dropped.
    - The controller reads `image_scan_jobs` through `getattr`.
    - `_q_bounds_by_operator_index` was removed.
    - `remove_operator_range` and `replace_operator_operands` are now unused.
  - Not done: the `docs/ARCHITECTURE.md` entry for `content_scan` and the `scan` kind, and the review. M0's Codex review (H23) and the directory tidy wait as well.
- **2026-11-19, owner rulings D1 to D12** (brief `plans/archive/cad-owner-decisions-for-astra.md`, Astra's advice `plans/archive/cad-owner-decisions-astra-advice.md`, Opus check `plans/archive/cad-owner-decisions-opus-check.md`). The owner took every recommendation:
  - D1: `id(doc)` is replaced by a process-unique handle generation; a replaced handle's results are released. H3 amended.
  - D2: A3b item 4 says only that the page's object analysis did not complete; N3 (`_read_payloads` outside the handler) is fixed with it. Owner wish for later: once there are more failure cases, the system should roughly tell which part of the analysis failed.
  - D3: zoom keeps a pending click. D4: an object batch is resolved in full before the first mutation. D6: fixed now. D11: a scan-specific message.
  - D5: M0 table select/delete is Windows-only with an explicit 'unsupported' message; the Mac/Linux port is a separate card later.
  - D7: every A3b/A5 addition beyond the cards is kept and is to be written into the card text.
  - D8: new card A6 (text hit and text index off the GUI thread), before Track B; Opus writes its design first.
  - D9: the splice writes its content stream compressed at zlib level 1; Q1 (1 s) is not relaxed.
  - D10: `get_image_rects` (image hashing) runs only on the branch that consumes it.
  - D12: the scans a page needs are admitted to the cache as one set; if they do not fit, the job ends `resource_limited`; failures are scoped to the document generation and the page frame. Opus writes the card first.
- **2026-11-19, D1 done in the tree (not committed).** `PDFModel.handle_generation` (+ `live_handle_generations()`), bumped in the `doc` setter next to `xref_epoch`; `DocumentSession.handle_generation`. `table_objects.frame_key` uses it. The `doc` setter and `close_session` call `table_objects.retire_dead_handles`, so a replaced or closed handle's results go at once; a store also drops older revisions of its own handle, and other tabs keep theirs (before, a store for tab B wiped tab A). The coordinator drops a late tables answer of any status, a crash included, for a stale key, without a message or retry (before, an old job's failure reached the new document; found by the Opus advisor pass). Red first: 6 new tests in `test_table_probe_non_mutation.py` (forced `id` collision across close/open, snapshot restore, same-handle reassign, tab switch, release on close, release on snapshot restore) and in `test_object_probe.py` the late `complete` answer plus 4 late-failure cases, each failing before the fix. table_probe_non_mutation 16, table_objects 11, object_probe 56, multi_tab_plan 118 (+1 skip), session_file_share_lock 29, secure_save_level 8, page_snapshot_identity 37, packed_save_failure_epoch 6, deleted_annotation 37, native_image_probe 32, content_scan 58 pass; ruff and mypy clean. B6's and H22's `(id(doc), edit_count)` guard text changed to the generation too.
- **2026-11-19, D1 review (plan-code-reviewer): ship.** Every guard proven by switching it off. Open for the owner:
  - **A (same class as D1, older): `edit_count` is not a revision.** Undo/redo never change it, and a page-snapshot undo keeps the handle, so `frame_key` stays the same while the page bytes change (reproduced with `AddTextboxCommand` + undo: the pre-undo table rects are still served). Also read in code: a failed handle renewal after save keeps the handle but sets `edit_count = 0`. Low impact today (object deletes use whole-document snapshots, which replace the handle); the H22 slice guard for B6 inherits it. Proposed class check: one parametrised test over every document-changing operation, its undo/redo and each save path, asserting "same `frame_key` implies same `scratch_page_bytes` digest"; likely fix a per-handle mutation counter bumped by execute, undo and redo.
  - **C (nit):** a stale tables answer is dropped silently, so the status "正在背景分析此頁的表格…" stays until another object status is set (older for `complete`; D1 extends it to failures). Suggested: on a stale drop, clear the status when no tables job is pending.
  - Astra's outcome test "a delete after a stale table answer leaves B's bytes unchanged" is not written; covered only indirectly through `frame_key`.
- **2026-11-19, owner: commit D1; fix A now; C and the missing outcome test go with D12.** D1 committed alone (A5 hunks in the shared files left unstaged). The commit also carries the A3b guard fix (`set_cropbox` inside `exact_set_key`, from the A5 tree), so `test_exact_object_text.py` passes at that commit.
- **2026-11-19, finding A fixed in the tree (not committed).** `CommandManager.revision` takes `next_revision()` at init and after every execute, record, undo and redo (in `finally`, so a refused or failed one counts); `DocumentSession.edit_revision` takes one on every `edit_count` write; `PDFModel.content_revision` is the pair; `frame_key` field 3 is now `content_revision`. Red first: `test_scripts/test_frame_key_revision.py` (undo, redo, an `edit_count` write of the same value, a replaced command manager, and the class check over add textbox / undo / redo / rotate / undo after save), 5 of 6 failing before the fix. Green: frame_key_revision 6, table_probe_non_mutation 16, object_probe 56, table_objects 11, exact_object_text 187, page_snapshot_identity 37, native_image_probe 32, object_controller_flow 26, undo_memory_budget 20, text_commit_undo_restore_identity 3, deleted_annotation 37; ruff and mypy clean.
