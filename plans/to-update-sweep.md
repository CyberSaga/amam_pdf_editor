# docs/to_Update.md sweep (2026-11-05)

## Current state and next step
- Owner asked (2026-11-05): fix every remaining item in `docs/to_Update.md`; skip the
  whole suite (memory pressure killed `run_suite.py` twice). Per-file red-light pytest
  still applies. Holdout A/B parity run is parked (thumbnail item is fixed here instead).
- Main tree already carries the uncommitted four-item adoption (Home/End, ribbon,
  delete default, inline custom range + Tab order); nothing committed yet.
- TODOS `[x]` ticks are not acceptance: an item without `→ OK` is re-checked in the real
  app before any code changes.
- 2026-11-05 end of session: S1, V9, V10, T1, B1, T2 fixed (per-file green; ruff + pre_push
  exit 0); docs (PITFALLS + index, ARCHITECTURE, TODOS, to_Update "已修（待確認）") done.
  NEXT: owner decisions on T3 deletion design and P* proposals; owner real-mouse checks of
  T1/T2; whole suite when memory allows. Nothing committed.

| # | Item (to_Update line) | Lane | Status |
|---|---|---|---|
| S1 | Search hit box lands on blank space (owner video 11-03, multicolumn.pdf @236%) | bug | FIXED: double scaling in `jump_to_result`; `test_search_jump_highlight.py` red 1/2 → 3 pass |
| V10 | Thumbnails fill/follow sidebar (10) | verify→fix | FIXED: 120 px height cap + 280 px width cap + list-width overflow; raster 270→380 px; `test_thumbnail_fill_width.py` red 3/4 → 4 pass; 06c1/06f rewritten (old cap contract superseded) |
| V9 | Window smaller / diagonal (9) | verify→fix | FIXED: min 720×520 → 480×360; compact shell shows 適應畫面/全螢幕 icon-only, hides duplicate 復原/重做; shell_tab_ux red 2 → 20 pass; real app 480×360 canvas 468×218 |
| V11 | Document centred (11) | verify | WORKS in real app (50 %: gaps 155/156 px; 75 %: 50/50) — owner to recheck |
| V13 | Tab × always visible (13) | verify | WORKS in real app (active + inactive tabs show ×, light theme) — owner to recheck |
| T1 | Thumbnail drag drop position (28) | bounded | FIXED (subagent): insertion line + slot helpers + source row at startDrag; red 6/8 → 8 pass; page_reorder 20, object_manipulation 45, multi_tab 118+1s; app screenshots in scratchpad/verify |
| B1 | Thumbnails vanish, only page numbers left (6) | repro | FIXED: `_release_thumbnail_pause` in `_cancel_page_render_for_session`; red 2 failed → 2 pass; resume_progress 7, page_render_coordinator 15, thumbnail_coordinator 22, survive_same_session 2 |
| T2 | Drag a detached window's tab back into the old window (25) | bounded | FIXED: `adopt_transferred_session` + main.py `hand_off_session`; code written first, red shown afterwards with HEAD main.py (stash): primary kept 1 tab; green 3 pass; tab_detach 13, single_instance_forwarding 22, forwarded_cli_focus 5 |
| T3 | Fully delete a text box (33) | proposal | CONFIRMED by probe: empty replacement → `REJECTED/empty_replacement` in run and paragraph mode, text stays, no message. Needs an engine deletion op that keeps neighbour positions (pdf-text-fidelity "不跳"); owner decides semantics |
| V* | Text-box edge resize (14), font size decimal (15), rect colour/width (16), print centring (12), notes as labels (17) | verify | pending real-app check (TODOS 3.1/3.2/3.5/3.7 claim done) |
| P5 | Taskbar/Explorer icon (5) | proposal | app icon == owner's reiya .ico (same SHA-256); `.pdf` → `PDFEditor.Document`, DefaultIcon = reiya ico; launch = `.venv\Scripts\pdf_editor.exe main.py "%1"` (venv launcher exe carries Python's icon). Not an app-code defect |
| P4 | Print cold-start ignores dialog (4) | proposal | dialog touched-field logic reads correct; needs owner printer + cold boot; propose diagnostic log of effective options/QPrinter state |
| P34 | Tables (34) | owner approved 11-05 | FIXED: `model/table_objects.py`; red 5/8 (HEAD object ops) → 11 pass incl. no-mutation guard (find_tables edits rotated pages: red 2/3 → pass); object suites 186/45/26/54/79/93 pass; real app office-report p3 select → Delete 442→275 chars → undo 442 |
| P4b | Print diagnostics (4) | owner approved 11-05 | DONE: `src/printing/print_diagnostics.py`; tests 4 + print suites; test runs redirected to os.devnull; owner prints after cold boot |
| P2/3 | Speed | owner approved "measure first" | MEASURED: `plans/perf-heavy-files.md`; raster-process plan awaits approval |
| P5b | Icon/association | owner approved | DONE on our side: owner ran the script (CyberSagaPDF + `cybersaga_pdf.exe`); Start-menu shortcut with AUMID + reiya icon created and read back. Owner: set default app, re-run script to clean legacy ProgID, re-pin |
| F | Recommendations (33 plan; 10-vs-28; 270-vs-380) | owner: "use Opus" | DONE via Opus workflow wf_50a91ea9-701: plan saved `plans/text-run-deletion.md` (awaits D1-D3); Q1 keep layout + timer edge scroll (red 5 → 13 pass); Q2 keep 380, 270 for > 400 pages (arithmetic 0.82 MB/page; red → 3 pass) |

## Proposals awaiting the owner (no code yet)
- P34 tables ("物件還是文字？"): treat a table as an OBJECT for select/move/delete and as
  TEXT for cell edits. Step 1: detect regions with `page.find_tables()` (PyMuPDF), show a
  frame in 操作物件 mode; Delete removes the region's text + ruling lines via redaction
  (one SnapshotCommand). Step 2: cell text edits reuse the existing edit-text engine (cells
  are ordinary text runs). Moving/resizing a native table is out (rewrites every cell).
- P2/P3 speed: measure first (`benchmark_ui_open_render.py`) on window open, file open and
  `test_files/hvac-dwg.pdf`; 3.6 root cause still stands (PyMuPDF holds the GIL, so the
  QThread offload cannot free the UI) → out-of-process rasteriser (pattern
  `src/printing/subprocess_runner.py`) + rescale-not-re-raster on wheel zoom. Own plan.
- P4 print cold start: add one INFO log line in the print helper with the effective
  options (override_fields, duplex, colour, copies) and the QPrinter state after
  `_apply_printer_options`; owner prints once after a cold boot, sends the log.
- P5 icon: the app already sets the right icon + AppUserModelID. Explorer/taskbar read the
  shortcut/exe icon: (a) a Start-menu shortcut with the same AppUserModelID and the reiya
  icon, pinned instead of the exe; (b) `ie4uinit.exe -show` to refresh the icon cache;
  (c) the packaged PyInstaller exe embeds the icon (TODOS PyInstaller section).

## Open trade-offs for the owner
- Item 10 vs 28: full-width thumbnails make rows 353 px (narrow) / 523 px (wide) on a
  640 px list, so only 1–2 drop targets are visible; the insertion line + 48 px edge
  auto-scroll carry reordering. Old 3.3 cap traded this the other way.
- Thumbnail raster 270→380 px ≈ 2× pixels per thumbnail, unmeasured; alternative: cap the
  left sidebar at ~300 px and keep 270.

## Fence log (found, not changed)
- PDFView has no WA_DeleteOnClose: a closed secondary window stays in
  `secondary_windows` (its model stays open) and `_try_promote_secondary` could promote
  a hidden one. Pre-existing for windows closed by hand.
- `_process_visible_render_batch` early return sets pending False unconditionally (can
  clear a newer batch's flag); a rejected render result (identity mismatch) never
  continues its batch. Not reproduced as a user symptom.
- `test_05_search_state_restored_per_tab` failed once under load, passes alone and in a
  later full-file run.
- Verify drivers: `view.close()` blocks on the unsaved-changes prompt after a reorder.

## Decisions
- `display_page(highlight_rect=)` now takes PDF points; the view scales with what it rendered.

## Running log
- S1: frames from the owner's video show result "頁 1" while the red box sits in blank
  space on page 2. `jump_to_result` passed `rect * scale`; the continuous branch maps
  through `_doc_rect_to_scene_rect` (× `_render_scale`) again. Red: 1 failed (2.36×),
  1 passed (1.0×). Green: new file 3 passed; search_enter_navigation 3 passed;
  mouse_gestures `-k search_jump` 1 passed. Single-page test is a guard (passes either way).
