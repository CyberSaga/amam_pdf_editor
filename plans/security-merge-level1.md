# Merge security/remediation-2026-11 into feat/true-text-edge-cases (level-1 secure save)

## Current state and next step

- Branch `merge/security-remediation` (worktree `pdf_editor_merge`, outside the main checkout) merges
  `origin/security/remediation-2026-11` (3 commits on base `fd0c4158`: `6554db9c`, `b7afe3de`, `5dc65697`)
  into `feat/true-text-edge-cases` at `c21ca03c` (25 local commits since the base).
- 11 conflicted files resolved, staged, NOT committed. Owner decision 2026-11-14: the security patches
  adapt to the local secure-save level 1 (`SECURE_SAVE_GARBAGE_LEVEL = 1`, commits `3fe8346f`, `4e7776ae`);
  the constant is not raised back to 4. Recorded here for later review (section "For review").
- Targeted run (21 security test files + local secure-save, leakage, garbage-level, thumbnail, hook
  registration, persistence files): 1372 passed after the test adaptations below. Pre-push gates (ruff, mypy,
  4 import-linter contracts, thread grep) pass.
- Full suite (`run_suite.py`, 4,494 s): 11,696 passed, 2 failed, 17 skipped, 0 hung, 0 crashed, 1 rc5-ok.
  Both failures: `test_text_commit_small_defects.py::test_a_save_always_invalidates_the_open_editors_preview_session`
  -- its fake model lacks `save_garbage_level`, which local `save()` reads (pre-existing on `c21ca03c`: test file
  and that line are unchanged by the merge). Fake fixed; the file reruns green.
- Independent static review (separate session, 2026-11-14): resolution matches the plan; no level-1 regression
  in CF5/CF17/CF18 paths. Follow-ups applied: move_page assertion tightened (finding 1), three stale
  `garbage=4` comments from the security branch reworded, large-document thumbnail height-cap test added.
  Affected files rerun: 62 passed; ruff clean.

## Conflict resolutions

| File | Local (HEAD) intent | Security branch intent | Resolution |
|---|---|---|---|
| `main.py` rejected-CLI dialog | create a QApplication (app id, icon) when a hand-off runs before one exists | CF6 `plain_text()` on file names | both |
| `controller/ocr_coordinator.py` imports | `retire_worker_with` | `plain_text` | union |
| `controller/print_coordinator.py` imports | print dialog / runner lazy-loaded | `plain_text` (eager imports were base text) | lazy kept + `plain_text` |
| `view/text_editing.py` imports | `ExtBSubsetService` lazy-loaded | F14 `css_font_family` | lazy kept + `css_font_family` |
| `model/pdf_optimizer.py` latched optimize save | chosen level, floored at `SECURE_SAVE_GARBAGE_LEVEL` | F8 `_save_target` (in-memory intermediate); `= 4` was base text | local level logic + `_save_target` |
| `utils/render_limits.py` thumbnail scale | width 380 px, 270 px above 400 pages | CF11 height cap 10x width | width selection, then cap = `MAX_THUMBNAIL_ASPECT` (10) x selected width |
| `controller/pdf_controller.py` `__init__` | `render_client` kwarg | `_annotations_numbering` (CF5) | both |
| `pdf_controller.py` save-done box | message names the garbage level used | `plain_text` | local message inside `plain_text` |
| `pdf_controller.py` save `finally` | bump render revision, reschedule visible render | CF5 `_refresh_annotations_if_renumbered()` | both, CF5 refresh first |
| `TODOS.md` | local sections | security residuals section; "Codex hook adapter" item | union; Codex item dropped (see below) |
| `docs/ARCHITECTURE.md` hooks | 11-11 hooks paragraph + full Codex CLI paragraph | base hooks paragraph + `fable_dispatch_guard` + short Codex paragraph | local paragraphs + the `fable_dispatch_guard` sentence |
| `docs/PITFALLS.md` | local entries | security entries | union minus two Codex-adapter entries |
| `docs/PITFALLS_INDEX.md` | | | regenerated |

## For review (owner)

1. **Secure-save level 1 vs the security branch's garbage=4 premises.** The branch's CF5/CF17/CF18 code and
   tests often say "a secure (garbage=4) save renumbers". Locally a latched save is level 1, which removes
   unreachable objects but does not compact/renumber. CF17 already used `garbage=1` and `_save_doc_packed`
   handles both. To review: whether deleted/replaced content is still absent from saved bytes at level 1 in every
   path the branch hardened, and whether the CF5 renumber refresh is now mostly dormant. Test results go below.
2. **`fable_dispatch_guard.py` (commit `6554db9c`) now registered beside the local `model_route_guard.py`.**
   Overlap: both deny `model: fable` spawns; the dispatch guard additionally denies inheriting dispatches
   (fork, `inherit` agents, named workflows) from a Fable main session. Keep both, or fold one into the other.
3. **Codex adapter docs dropped.** The security branch's TODO "Codex hook adapter", its short ARCHITECTURE
   paragraph and two PITFALLS entries describe a Codex adapter (`test_codex_hook_adapter.py`) that is in
   neither tree (uncommitted on the remote machine). Two of them name possible real gaps in the local
   `scripts/hooks/codex_hook.py`: the canonical `spawn_agent` tool name is not matched (only
   `collaborationspawn_agent`), and `ruff format` flag detection may scan the whole command instead of each
   segment. Check and port if real.
4. Security branch residuals (F4, F13, F15, F25, signed history, OCR policy) are carried over in TODOS.md.
5. Review notes: at production level the CF5 refresh never fires (the production-level parametrizations only
   prove "no renumbering"; the refresh logic is covered by the pinned-4 cases). `_atomic_full_save`'s default
   `garbage=4` has no production caller (all pass `SECURE_SAVE_GARBAGE_LEVEL`). `model/pdf_model.py:511`
   ("print / export / merge still use 4") is a stale local comment, not from this merge.

Evidence for item 1: every deleted/replaced-content byte test passes at level 1
(`test_deleted_annotation_not_in_saved_bytes`, `test_unsigned_save_drops_replaced_content`,
`test_full_save_object_streams`, `test_full_save_acceptance_oracle`, the leakage `== []` cases). At level 1 a
latched save keeps the numbering, so the CF5 refresh runs but finds nothing to refresh; it stays live for any
renumbering save (floor raised, or a future level-2+ path).

## Test adaptations (fixture premises only; end-property assertions unchanged)

| Test | Failure after merge | Adaptation |
|---|---|---|
| `test_note_xrefs_survive_renumbering_save.py` (3 tests) | premise "the save must be the renumbering rewrite" false at level 1 | parametrized: production level (premise flipped to numbering kept) and floor pinned to 4 (original premise); same end assertions |
| `test_packed_save_failure_epoch.py` refresh-open-note | `new_xref != old_xref` false at level 1 | same two-level parametrization; premise `(new != old) == renumbers` |
| `test_packed_save_failure_epoch.py` publishes-changed-numbering, notifies-once | subject is a renumbering pack | floor pinned to 4 |
| `test_secure_save_leakage.py` move_page (local test) | CF18 object-stream packing puts the live title inside an `/ObjStm`, giving extra `stream`/`stream_raw` hits | NOT premise-only (review finding 1): the assertion now accepts container hits, limited to at most ONE container xref, of type `/ObjStm`, holding the marker exactly once in total; exactly one `object` hit still required; `_marker_hits` unchanged. An orphan packed into a second container still fails |
| `test_text_commit_small_defects.py` save-invalidates-preview (pre-existing) | fake model lacked `save_garbage_level` | fake gets `save_garbage_level=1` |
| `test_font_family_markup_inert.py` (16) | patched `view.text_editing.htmlbox_args_with_ext_b`, which local work made a call-time import | patch `utils.cjk_ext_b_font.htmlbox_args_with_ext_b` |
| `test_message_text_plain.py` save box (4) | fake model lacked `save_garbage_level`; local message names the level | fake gets `save_garbage_level=1`; expected text is the local message, still compared raw |
| `test_claude_settings_hooks.py` | `fable_dispatch_guard.py` registered but not in `EXPECTED` | added with its Agent/Workflow matcher |

Coverage checks: F8 -- the only `.save(str(` left in `model/pdf_optimizer.py` is the plaintext-source pikepdf
repack; encrypted sources take the in-memory branch. CF6 -- `test_every_message_box_text_is_constant_or_wrapped`
scans every file that opens a message box (the set matches a repo grep); `show_error` wraps internally.

## Log

- 2026-11-14: worktree created from `c21ca03c`; `.venv` and `test_files` copied (no junctions).
- 2026-11-14: merge started, 11 conflicts resolved as above.
