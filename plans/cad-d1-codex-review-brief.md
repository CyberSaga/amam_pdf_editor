# Codex review brief: CAD D1 commits `ebb86561` and `71fa1ba9`

Status: written 2026-11-19 by Opus; not dispatched. The owner hands it to Codex. Codex is the defensive reviewer (handoff Q3, H23); Opus accepts or rejects each finding in writing.

## Scope

Review only these two commits: `git show ebb86561` and `git show 71fa1ba9`. The working tree holds uncommitted card A5 work (`model/content_scan.py`, image-scan code in `pdf_content_ops.py`, `pdf_object_ops.py`, the controller and `helper_main.py`). It is out of scope. Read-only: no edits, no commits, `.venv\Scripts\python.exe -m pytest <one file>` only, one at a time.

## What the commits claim

**`ebb86561`: handle identity (owner decision D1).**
- Before: `table_objects.frame_key` used `id(doc)`. CPython reuses that after a document closes, so doc A's tables and failed marks showed on doc B, and Delete erased B's text (A3 review B2).
- Now: `PDFModel.handle_generation` is a process-unique counter, taken in the `doc` setter on every handle replacement. Nothing restores it, unlike `xref_epoch`.
- `table_objects.retire_dead_handles` runs from the setter and from `close_session`. It drops results of handles no tab holds; other tabs keep theirs.
- `ObjectProbeCoordinator._is_stale` drops a late tables answer of any status (a crash included) for a stale key, with no message and no retry.
- Also carries the A3b guard fix: `set_cropbox` runs inside `exact_set_key`.

**`71fa1ba9`: revision (D1 review finding A).**
- Before: `edit_count` served as the revision. Undo and redo never change it, a save resets it, and a page-snapshot undo keeps the handle, so a pre-undo table answer was still served after the undo.
- Now: `PDFModel.content_revision` is a pair of never-repeated ticks (`edit_commands.next_revision`):
  - one on every `edit_count` write;
  - `CommandManager.revision`, after every execute, record, undo and redo, in `finally`.

**Governing text:** `plans/cad-vector-object-editing-handoff.md`, H3 (line ~30), H22 (line ~53), and the 2026-11-19 running-log entries. Owner rulings and their background: `plans/archive/cad-owner-decisions-*.md`.

## Questions for Codex

1. **Handle replacement.**
   - Does any path install or replace a live `fitz.Document` without going through the `PDFModel.doc` setter? Look for direct `session.doc =`, `_legacy_doc =`, `DocumentSession(...)` construction, and tab transfer between models.
   - Is there one where `handle_generation` stays the same while the handle changes?
2. **Document changes the revision misses.**
   - Does any path change page content, annotations or boxes with no command execute, record, undo or redo, and no `edit_count` write? Candidates:
     - `rotate_pages`: covered by the rotation field;
     - optimize;
     - redaction;
     - OCR;
     - watermark;
     - form fill;
     - any controller path that edits `model.doc` directly.
   - Name each one, and say whether `test_frame_key_revision.py::test_a_changed_page_never_keeps_its_frame_key` would catch it if added to `_OPS`.
3. **Retirement.**
   - Can `retire_dead_handles` drop a result that a live tab still needs?
   - `live_handle_generations()` covers sessions plus the legacy doc. Does `PDFModel.close()` leave entries behind? The reviewer noted that as memory-only.
4. **Stale drop.**
   - `_is_stale` returns before `probe_failed` or `tables_ready`. Is there a caller that waits for one of those signals and so can hang?
   - Known: the status-bar text "正在背景分析此頁的表格…" stays. That is already scheduled with D12; do not re-report it.
5. **Ordering in `CommandManager`.**
   - Tick in `finally` after `cmd.execute()` / `cmd.undo()`. Can a frame key be computed inside a command (a nested `processEvents`, a signal) and match after it ends?
   - Does `record()` (tick before the push) leave a window where the operation already ran but the revision is the old one?
6. **Tests.** Does each new test fail on the parent commit for the stated reason? Opus showed red light. Re-check `test_frame_key_revision.py` and the last six tests of `test_table_probe_non_mutation.py`.
7. **Class question.** Is any finding another instance of a class already named here (identity reuse, a restored epoch, a revision that misses a change)? If so, give the single outcome check that closes it, not another list of causes.

## Known and not to be reported

- These are scheduled with D12:
  - the status-bar override after a stale drop;
  - Astra's missing outcome test "a delete after a stale table answer leaves B's bytes unchanged".
- Anything in the uncommitted A5 tree.
- Pending jobs of a retired handle are not cancelled; only their answers are dropped. Accepted, since the cost is one wasted child run.

## Answer format

Write `plans/cad-d1-codex-review-r1.md`, with the `Recurrence` section that review records need. Put a table at the top, one row per finding: id, severity (blocks / should fix / nit), file:line, one-sentence claim, how you showed it (ran a script / read code). Below the table, one section per finding with the evidence.
