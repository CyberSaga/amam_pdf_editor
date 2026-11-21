# A6 design card: text hit and text index off the GUI thread (owner D8)

Status: DESIGN ONLY (Opus deep-reasoner, 2026-11-21). Nothing profiled: every cost marked "inferred" was read from code. Implementer: Sonnet. Not started; owner answers Q1-Q5 gate A6.3 onwards.

## Why
Still in KNOWN_OVER_LIMIT: test_gui_stall.py (four images-fixture gestures, two path-heavy browse right-clicks) and test_cad_sample_click.py (CAD browse right-click, 1437 ms). D8 orders this card before Track B. H3/F1, H4, H5, H14, H15, H16 apply unchanged.

## 1. GUI-thread cost per gesture
| Gesture | Step | Cost | Source |
|---|---|---|---|
| CAD p1 browse right-click, cold | whole gesture | 1437 ms | TODOS |
| same | _build_page_index: one content_textpage(page,0) | ~400 ms (inferred split) | text_block.py:156-158 |
| same | plain lines content_text(page,"text"): second interpretation | ~400 ms (inferred) | text_block_parsing.py:519 |
| same | miss fallback content_text(page,"dict",flags=0), never cached | ~400 ms (inferred) | pdf_model.py:3501-3506 |
| CAD warm | fallback only | 406 ms | TODOS |
| form/paths browse right-click | first index build, 200k paths | ~120 ms | test_gui_stall.py:26 |
| images, four gestures | with warm() polls / completion signal | 246-327 / 121-231 ms | handoff:22 |
| images | one scratch_page_bytes per click | ~85-125 ms | TODOS; pdf_controller.py:3349 |
| images tables delivery | _current_input copy, then lookup_object_at_point builds a second | 2 x 85-125 ms (inferred) | coordinator:175,215-220 |
| enter text-edit mode | prewarm ensure_page_index_built per visible page | ~800 ms per CAD page (inferred) | pdf_view.py:5766-5778 |
| page insert/delete | stale drain 5 pages per tick inline | up to 5 x 800 ms (inferred) | pdf_controller.py:5173-5179 |
| undo/redo | refresh_structural_indexes inline | ~800 ms per CAD page (inferred) | pdf_model.py:2108-2128 |

## 2. Design
Recommended answers to Q1-Q5 are assumed.

**D-A6-1 Child, not QThread.** PyMuPDF holds the GIL in MuPDF calls (07-17 archive, PITFALLS:6025); content_textpage writes the live page (set_rotation, page_content_text.py:74-92); only the GUI thread may read the live doc (H22). So: new child kind `text` on the existing runner (H16, H24 cap). M2 re-measures; that number decides.

**D-A6-2 Pure half / install half (no Qt).** text_block.py: extract_page_entry(page_num, page) -> PageIndexEntry (frozen: blocks, spans, paragraphs, run_map, plain_lines, fallback_rows); TextBlockManager.install_page_entry; _build_page_index = install(extract). to_json/from_json: Rect/Point as float lists, color and dir_vec rebuilt as tuple, run_ids list[str], declaration order (text_block_parsing.py:143-191), is_vertical not serialised. FallbackRow(block_idx, bbox, font, size, color_int, rotation, text) from the same flags-0 dict blocks; text from _compose_block_text_for_hit moved to a pure function. Fallback (pdf_model.py:3504-3542) reads get_fallback_rows and interprets nothing. Trap: new store joins the store lists at text_block.py:46-51, 76, 96, 139.

**D-A6-3 Child kind.** Payloads: one-page scratch copy (same bytes as tables) and ASCII 0-based page index. Child calls fitz_setup.apply_production_tools() first (TOOLS parity, verify.py:205-206). Answer {"v":2,"status":"complete","entry":...}; failures as helper_main.py:96-113. Trap: runner _parse must accept `entry` (A5 dropped every scan answer this way, handoff:456).

**D-A6-4 Routing.** model/text_index_jobs.py (pure): TEXT_INLINE_LIMIT_BYTES (start 65,536); text_index_cost_bytes = raw /Contents plus reachable Form XObject lengths (visited set, stop over limit or past 256 forms). Routing only, never admission. Inline when under limit, no contained child, or key marked failed.

**D-A6-5 Staleness.** Job key = PageInput.key (page, sha256 of copy). install_text_index(job_key, entry, current) installs only if table_objects.key_is_current: installed / already_clean (keep, emit ready) / stale (drop, emit probe_dropped("text", page)). Failed keys: LRU 256. no_headroom and unsupported_platform mark nothing. (handle_generation, content_revision, page) only dedups in-flight requests (hover). No revision admits anything.

**D-A6-6 Coordinator/runner/controller.** request_text_index(page_num, page_input) shaped like request_tables, dedup by key, returns at once off Windows, signal text_index_ready(int). _current_input/_is_stale cover tables and text. Job.front kept on retry. Runner submit(..., front=False): front inserts before waiting jobs, never kills a running one. Controller: kind=="text" branches first in _on_object_probe_failed/_dropped (3511-3541): drop only the pending text click, clear only _text_status_message, never touch object status or the pending object click, route page inline. _PENDING_TEXTS gains "text".

**D-A6-7 One copy per slot.** Coordinator holds delivery_input while emitting tables_ready/text_index_ready; _on_object_tables_ready passes it to resolve_pending_object_click -> lookup_object_at_point(page_input=). Menu: controller.resolve_menu_hits(page, point, mode) -> (object_hit, text_hit), one PageInput, text first; pdf_view.py:6377-6378 calls it. No model object enters the view.

**D-A6-8 Controller gate (H15: model functions stay blocking).** Non-blocking twins returning TEXT_LOOKUP_PENDING (singleton in model/object_requests.py): lookup_text_at_point, lookup_char_context_at_point, lookup_text_selection_lines, lookup_text_in_rect, lookup_text_targets. _text_index_gate -> ready | inline (busy cursor + ensure_page_index_built) | pending (request front=True + status "正在分析此頁文字…" when no object status). Originals stay for tests/scripts. request_page_index(page)->bool serves prewarm and drain; never builds a child-routed page inline.

**D-A6-9 View while pending.** Every `if info:` (4652, 4710, 5829) checks TEXT_LOOKUP_PENDING first. Browse press/selection/doc rect: miss, no replay. Hover: no highlight. Menu: disabled "正在分析此頁文字…" instead of Edit Text, not reopened. Char context, selection lines, Select All, outline targets: status only. Text-edit press: PendingTextClick(page, x, y, mode, generation); generation changes on any press, set_mode, tab/doc change, _finalize_text_edit; on text_index_ready with same generation look up again and _open_editor_from_hit (4715-4735 extracted). Prewarm: request_page_index per visible page, at most one inline build per slot. Stale drain: inline-routed pages only, one per slot.

**D-A6-10 Failure/refusal.** Text is never refused (scan precedent coordinator:120-121; tables stay refused off Windows, D5). resource_limited / analysis_failed / containment_failed / two crashes mark the key; next gesture builds inline with busy cursor and "正在分析此頁文字（前景）…". no_headroom builds inline. Gap over 100 ms accepted only on that inline path and off Windows.

## 3. Sub-steps
Free now: A6.0, A6.1, A6.2 (need only M1). A6.3+ wait on M2, M4, M6 and Q2, Q3, Q5.

**A6.0 Measure** (plans/cad-vector-object-editing-probes/p20_text_index_offload.py, product functions only):
- M1 cProfile CAD browse right-click cold/warm: content_textpage calls and ms per caller, SourceRunResolver ms. Stop if fallback < 80 % of warm gesture.
- M2 heartbeat gap while a QThread runs extract_page_entry on a scratch-copy handle of CAD p1. <= 100 ms: stop (design becomes QThread; owner). Else child stays.
- M3 median of 5: insert_pdf, tobytes, sha256 on images/paths/form fixtures, CAD p1, hvac-dwg p29.
- M4 child round trip on CAD p1: spawn-to-answer, answer bytes, GUI-side json.loads + from_json + install. Install > 60 ms: stop.
- M5 in-process build ms vs text_index_cost_bytes; halve the limit until every under-limit page builds in <= 60 ms; add image XObject lengths to the cost if the images page stays over; stop if still over or limit < 8,192.
- M6 extract(scratch copy) vs extract(live page): OC group OFF in /OCProperties (does insert_pdf carry it?), four rotations, Type0/CID, CAD p1. Any difference: stop. Either way add a TODOS line for the tables child.

**A6.1 Cache the fallback.** Red test_text_index_fallback.py: second get_text_info_at_point(allow_fallback=True) at a miss makes 0 content_textpage calls (today 1); rows-based fallback returns the same TextHit as old code (fixtures, rotations, miss); insert/delete/move keep rows aligned.

**A6.2 One copy per delivery slot.** Red (stub runner): a pending left click's tables delivery makes 1 scratch_page_bytes call (today 2). Re-measure images entries; none retires yet.

**A6.3 Pure/install halves, child kind.** Red test_text_index_entry.py: install(from_json(to_json(extract(p)))) equals _build_page_index(p) field by field on M6 pages. Red test_object_probe_child_v2.py: real child text answer equals in-process extract on the scratch copy; child TOOLS equal the app's; runner parses entry. test_page_content_text.py unchanged.

**A6.4 Coordinator, priority, gate, routing, controller slots.** Red (stub runner): cold child-routed page returns TEXT_LOOKUP_PENDING and queues one front job; retry keeps front; second hover same triple makes no copy/job; ready installs and leaves page clean; already_clean; failure marks key then inline; no_headroom inline; off Windows (patched) and under-limit inline with no job; text failure during a pending object click leaves click and object status unchanged; PDFController.__init__ starts nothing. Class check (outcome): for every operation in test_frame_key_revision.py's list plus undo/redo: request, operate, deliver; installed index equals extract_page_entry of the live page.

**A6.5 View sites.** Red test_text_hit_pending.py: menu shows disabled text entry, no Edit Text; pending text-edit press opens editor on ready, newer press/mode/tab change drops it; browse press and hover never replay; guard: zero get_text_info_at_point( calls under view/, every lookup_text_*( site allowlisted with its pending test.

**A6.6 Prewarm and drain.** Red: entering text-edit mode on a child-routed page builds nothing inline; drain after page delete starts no child, builds <= 1 page per slot.

**A6.7 Scratch copy at the gesture (rule on M3).** Images copy <= 70 ms: nothing to build. Otherwise stop and ask Q1. No two-slot copy (warm menus would always show pending).

**A6.8 Harness and acceptance.** Add gui_stall_probe.TextAnswerWatch (text_index_ready, probe_failed("text")) and a combined watch; test_gui_stall.warm() uses the watches (Q4); add gesture "enter text edit mode" to both stall tests. Accept: ("form","right click in browse"), ("paths","right click in browse") and CAD "right click in browse" leave KNOWN_OVER_LIMIT; mode entry <= 100 ms; four images entries leave only under A6.7's first branch, else stay with cause "bytes-key copy (F1), Q1"; ARCHITECTURE (kind text, gate, priority), PITFALLS (child TOOLS parity; TextBlockManager store lists), TODOS lines 5 and 7 updated.

**Stop (whole card):** any M-rule says stop; an existing test asserts the fallback interprets the page; SourceRunResolver on a CAD hit > 60 ms (outside this card).

## 4. Risks, dead ends, owner questions
Risks: (1) scratch copy extracts differently from live page (M6 gates); (2) JSON answer size on dense pages (M4); (3) text waits behind a running tables job (12.6 s on the sample; front does not preempt, Q3); (4) inline rebuilds remain on commit (rebuild_page) and undo (pdf_model.py:2108-2128), unverified whether commits rebuild or mark stale; (5) _draw_all_block_outlines reads controller.model directly (pdf_view.py:5752), untouched.
Dead ends: QThread on scratch bytes (GIL); admission by content_revision/page_state (handoff:481-484); merging flags-0 and TEXTFLAGS_TEXT interpretations (fidelity change); two-slot copy; always using the child (spawn delay on small pages, unmeasured).

Owner questions (recommendation first):
- **Q1 images copy > 70 ms:** (i) keep four entries with cause F1; (ii) revision memo for gestures only (reopens H3 class); (iii) cheaper copy, still bytes-by-construction. Rec: (iii) if M3 shows one dominant step with a library fix, else (i); never (ii). Changes A6.7 and A6.8 accept only.
- **Q2 off Windows and on text-job failure:** build in-process (gap accepted only there), never refuse text. Rec yes. Alternative changes D-A6-10 and A6.4 failure tests.
- **Q3 text priority:** front of FIFO vs second concurrent child (second H24 lease). Rec: front now; second lane only if the measured wait hurts. Changes D-A6-6 and A6.4 priority tests.
- **Q4 switch test_gui_stall.warm() to signal watches (TODOS:10) inside A6.** Rec yes (121-231 ms figures assume it).
- **Q5 text-edit press while pending:** replay as data (open editor on ready, H4 generation) vs refuse "repeat when ready". Rec replay (opens an editor, writes nothing). Changes D-A6-9 text-edit bullet and two A6.5 tests.

Unchecked: _schedule_index_batch has no caller (Grep only); whether the pyproject view-no-model allowlist covers model/object_requests.py.

## 5. Owner decisions and measured results (2026-11-21)
- A6.0 run (probe p20): M1 cold 762 ms / warm 254 ms, fallback = 100 % of warm (A6.1 goes ahead); M2 heartbeat gap 251 ms of 256 ms (GIL held: child, not QThread); M3 images copy 94 ms (insert_pdf 31 + tobytes 62 + sha256 10; tobytes flags change nothing; blake2b 39 ms; raw-stream digest without copy 53 ms); other fixtures 2 to 7 ms; M4 child spawn + import fitz ~86 ms, a 22 KB answer parses in 0.1 ms; M5 limit 65,536 separates hvac (7.5 KB, 14.5 ms) from the rest (1.4 to 2.1 MB, 77 to 508 ms), the images page costs 30 ms in-process; the CAD page has no editable text (index empty, the 400 to 500 ms is pure interpretation).
- M6 stop fired: `insert_pdf` drops `/OCProperties`. Fixed in `table_objects.scratch_page_bytes` (`_carry_ocproperties`, lockstep walk); the text child reads the same copy and is no longer blocked by it.
- Q1: owner agreed with Astra: option (i). The four images entries stay in `KNOWN_OVER_LIMIT`, cause "bytes-key copy (F1), Q1" (no cheaper exact-bytes copy exists: measured).
- Q2 to Q5: owner took the recommendations (inline fallback, never refuse text; text at the front of the queue; `warm()` on the signal watches; replay a pending text-edit press).
