# CAD M0 (A3 to A5): open owner decisions, brief for Astra

Status: open. Written 2026-11-18 by Opus. The owner hands this brief to Astra (Codex, gpt-6-astra) to investigate each decision and recommend one option. Opus then reads the advice, checks it, and puts the decisions to the owner. **Astra advises; it does not decide and does not implement.**

Governing plan: `plans/cad-vector-object-editing-handoff.md` (decisions H1 to H24, cards A1 to A5, running log at the bottom). The source for every item below is in that log, in the entries dated 2026-11-18. Read those entries first.

## Tree state

- Committed: A1, A2 (`0fdafd7d`), A3 + A3b (`2be2e3b1`), A4 (`a441a844`).
- **A5 is uncommitted in the working tree.** Changed files: `controller/object_probe_coordinator.py`, `controller/object_probe_runner.py`, `controller/pdf_controller.py`, `model/pdf_content_ops.py`, `model/pdf_model.py`, `model/pdf_object_ops.py`, `model/table_objects.py`, `src/object_probe/helper_main.py`, `test_scripts/test_object_probe_runner.py`. New files: `model/content_scan.py`, `test_scripts/test_content_scan.py`, `test_scripts/test_native_image_ops_stall.py`, `test_scripts/test_native_image_probe.py`. Do not modify, stash, reset or commit any of them.

## Rules for Astra

1. Read-only on the tree. Write exactly one file, the advice file named below. Probe scripts go in a temporary directory outside the repo, and the advice file quotes the commands and their output.
2. Python: `.venv\Scripts\python.exe` only (pinned PyMuPDF 1.27). One pytest at a time: `.venv\Scripts\python.exe -m pytest <file> -q --tb=short`. Never `pytest test_scripts/` in one process.
3. A claim about a library (PyMuPDF, MuPDF, Qt) is measured or quoted from the installed source with `file:line`. If a claim is not measured, label it `unmeasured`.
4. No machine-specific data in the advice file: no home paths, user names or host names. Use repo-relative paths.
5. Do not reopen a decision the owner already made (H1 to H24 as amended, the A3 rulings of 2026-11-18). If the evidence says that a made decision is wrong, record that under "Challenges to made decisions" at the end of the advice file. Do not fold it into a recommendation.

## Decisions

Each item gives what is known and the options Opus sees. Astra may add an option, and must say why when it does.

### D1. Table cache and failed set leak across documents (A3 review B2). Highest priority.
`id(doc)` is reused after `close_session` (9 of 20 cycles). `_CACHES`/`_FAILED` in `model/table_objects.py` (A2 and earlier, plus the A3b failed set) then serve doc A's answer for doc B. Proven destructive: `delete_objects_atomic` erased doc B's text.
Options: (a) clear both maps on session open and close; (b) key on a token that is never reused (a per-session counter); (c) both. Either one changes H3.
Also say: are there other `id(doc)`-keyed caches with the same flaw? List every site you find (grep `id(doc` and `id(self.doc`), including A5's `content_scan` cache and alias map.

### D2. `resource_limited` is unreachable inside `find_tables` (A3 review B1)
`pymupdf/table.py:2720-2722` catches every `Exception`, and MuPDF's native errors are not `MemoryError`. A child that runs out of memory answers `analysis_failed` ("analysis failed") instead of the memory message. Item 4 of A3b assumed otherwise.
Options: (a) accept the mapping and change the message; (b) detect the memory cap in the child some other way (for example, job-object accounting or peak working set against the cap) and map it to `resource_limited`; (c) something else. Measure what the child can actually observe when it hits the cap.

### D3. Zoom cancels a pending click (A3 review N1)
`change_scale` → `_clear_object_selection` → `bump_object_click_generation`. H4 says scroll and zoom do not cancel a pending click; the code follows A3 item 5 literally.
Options: (a) keep the generation across zoom (separate "clear selection" from "cancel pending click"); (b) amend H4 to accept that zoom cancels.

### D4. Batch delete runs `find_tables` on the GUI thread (A3 review N2)
In a multi-select delete, the first delete bumps `edit_count`, so the second table's lookup misses the cache and analyses on the GUI thread (`controller/pdf_controller.py:3515`). This breaks H14/H15.
Options: (a) resolve every table in the selection before the first mutation; (b) refuse a multi-table delete until each table has a fresh answer, and request them off-thread; (c) something else.

### D5. Table select and delete never work off Windows (A3 review N3)
`read_system_memory()` returns `None` off Windows, so every job is `no_headroom`, and the message tells the user to try later.
Options: (a) implement memory reading for Linux/macOS; (b) when memory cannot be read, run with the fixed cap only; (c) keep it and change the message. Note what CI (Linux/macOS legs) currently exercises.

### D6. Context menu shows "Delete Object" under the disabled "analysing" entry (A3 review, minor)
`view/pdf_view.py:6381-6390`, with an older selection present. Recommend whether to fix now, with which behaviour, or to defer.

### D7. Additions beyond the cards (A3 and A3b)
Confirm or reject each, with a one-line reason:
- A3b: the CropBox restore after `page_rotation_reset` in `page_has_table_text` (parity fails on `cropped_rot90`/`cropped_rot270` without it). It now runs inside `exact_set_key` (an uncommitted fix in the A5 tree).
- A3b: the coordinator's early-answer buffer for answers the runner emits inside `submit()`.
- A3b: the new child tests are in `test_object_probe_child_v2.py`, not in `test_object_probe_child.py`.
- A3: `ObjectProbeRunner.is_waiting`; the coordinator's `runner=` injection argument; the view fallback to `get_object_info_at_point` for test doubles; a pending press is not swallowed in text-edit mode; the child sends Python stdout to stderr.

### D8. Text hit and text index on the GUI thread (A4, plus two A5 gestures)
On the CAD sample, a right-click in 瀏覽 (browse) takes 1,346 to 1,437 ms: `get_text_info_at_point` → `page_content_text.content_textpage` runs `fz_run_page_contents` three times (about 400 ms each), plus a first `ensure_page_index_built` of about 800 ms. A warm repeat still takes 406 ms. The two non-image `test_gui_stall` gestures (form/paths, browse) are the same class.
Options: (a) a new card that moves the text hit off the GUI thread; (b) a new card that builds one `content_textpage` per page and reuses it; (c) both; (d) accept it and keep the `KNOWN_OVER_LIMIT` entries. If a card is recommended, state its Accept criteria and where it goes in the order (before or after Track B).

### D9. Deflate cost of the byte splice (A5 Accept item 2)
On the 200,000-path image page, move, resize, rotate and delete take 1,082 to 1,241 ms against Q1 (1 s). About 0.59 s of that is `doc.update_stream` deflating the 4.3 MB stream. Undo takes 375 to 433 ms.
Options: (a) `compress=0` for the spliced stream (measure the file-size change and whether save with `garbage`/`deflate` recompresses it later); (b) a lower deflate level, if PyMuPDF exposes one (quote the source); (c) defer the compression to save; (d) amend Q1 for pages above a size threshold. Measure the edit time and the saved file size for each option on the A5 test fixture (`test_native_image_ops_stall.py` builds it).

### D10. `get_image_rects` cost (A5 Accept items 1 and 3)
`page.get_image_rects` MD5-hashes the image pixmaps: 313 to 380 ms on the images fixture (3 × 16 MB), about 57 ms on the 200,000-path page, where the answered click (115 to 119 ms, limit 100 ms) reruns discovery. A5 kept `get_image_rects`; the `INLINE_SCAN_LIMIT_BYTES` halving rule cannot help, because that content stream is tiny.
Options: (a) get image rects from the A5 content scan (the `Do` operators and CTMs it already records) and drop `get_image_rects` on this path; (b) call `get_image_rects` with hashing off, if the API allows it (quote the source); (c) cache the discovery result per page key, so the answered click does not rerun it; (d) move discovery into the scan child. Say which one closes all four images-fixture gestures and the click, and what parity risk each carries (inline images, Form XObjects, clipped images).

### D11. Message for a scan that ends `resource_limited` (A5 Accept item 4)
It currently reuses the table message. Propose the Traditional Chinese wording (and the English key, if the UI uses one), consistent with the existing table messages.

### D12. A5 implementer's judgement calls
Confirm or reject each, with a one-line reason:
1. A single scan larger than the 200,000-record cap is stored alone (the LRU does not refuse it).
2. `derive_after_remove` raises `ValueError` when the removed range holds no `Do`.
3. The failed scan keys live in `content_scan` (`mark_scan_failed`/`scan_failed`), not in the coordinator's `failed_scan_keys`.
4. The runner's `_parse` now accepts `scans` (without it, every scan answer was dropped).
5. The controller reads `image_scan_jobs` through `getattr`.
6. `_q_bounds_by_operator_index` was removed.
7. `remove_operator_range` and `replace_operator_operands` are now unused: delete them, or keep them.

## How Astra writes the advice

Write one file: `plans/cad-owner-decisions-astra-advice.md`. Do not edit this brief.

### Header (at most 15 lines)

- Model and effort, date, and the git `HEAD` hash at the time of the investigation. (Uncommitted files are not included.)
- One table with one row per decision: `ID | recommended option | confidence (high / medium / low) | needs owner word (yes / no) | blocks A5 commit (yes / no)`.
- Recommended order of the work, as one line of IDs (for example `D1 > D9 > D10 > ...`).

### One section per decision, in this shape

```
## D<n>. <title from the brief>

Recommendation: <one option letter, or "new: <name>">, in one sentence.

Evidence:
- <fact> (measured: <command>, output below) | (source: <path>:<line>) | (unmeasured)

Why not the others:
- <option>: <one line>

Change it implies:
- Files and functions (path:line), and which H<n> or card text changes, quoted before and after.
- Tests: the red-light test to write first (file, test name, what it asserts).

Risks: <what could break, and how a test would catch it>.
```

Rules for the sections:
- One recommendation per decision. If two options are close, pick one and name the fact that would flip it.
- Under "Evidence", quote output and source verbatim and keep each quote under 20 lines. Put long output in an appendix at the end of the file, and refer to it by heading.
- No code patches. A function signature or a few lines of pseudocode is fine when it makes a design unambiguous.
- When an item has nothing to investigate (D6, D7, parts of D12), a recommendation and a one-line reason are enough.

### Closing sections

- `## Challenges to made decisions`: per rule 5 (empty if none).
- `## New findings`: any defect found on the way that is not in D1 to D12, with a repro. Say for each whether it blocks the A5 commit.
- `## Appendix`: long outputs and probe scripts, verbatim.

## What Opus does with the advice

Opus checks every `measured` claim that a recommendation rests on (re-runs the command or reads the line), marks each D as agreed, disagreed (with the reason) or needs-more, and puts the result to the owner. Owner rulings go into the handoff log; this brief and the advice file are then `git mv`ed to `plans/archive/`.
