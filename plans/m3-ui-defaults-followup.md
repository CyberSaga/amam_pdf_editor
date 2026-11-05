# M3 UI defaults follow-up

## Current state and next step
- Scope: Home/End from canvas and ribbon; ribbon document-presence default;
  delete defaults to current page; inline custom ranges for delete/rotate.
- Existing owner change: `.codex/hooks.json`; leave untouched.
- Implementation verified; overall acceptance PARTIAL because suite is not green.
- Red: 6 failed, 6 passed. Scoped tests: 12 + 6 + 19 + 118 passed, 1 skipped.
- Supervised app: exit 0. Pre-push gates: exit 0. Pitfalls index/status docs updated.
- Suite: exit 1; 9769 passed, 26 failed, 203 skipped, 0 hung/crashed.
- Done-map: production/test/docs changes complete; independent code review found
  no correctness defect; all scoped app flows verified (file-selection I/O supplied).
- Pending: 17 suite failures depend on missing/insufficient corpus; 9 fail at local
  socket listen. Independent QtCore/QtNetwork probe reproduces access denied.
- Next: owner environment/fixtures must be restored before rerunning the suite;
  do not change out-of-scope tests, single-instance code or corpus in this task.
- Keep plan active, not archived, while whole-suite acceptance remains incomplete.
- Then implement only in View, update existing range tests and requested docs,
  run targeted files, supervised real app, suite, lint and layer checks.
- Independent plan-code-reviewer must review final diff before completion.

## Goal and modules
- `view/pdf_view.py`: retain signal routing and existing page-key handler guards;
  switch ribbon only on document-presence transitions; share range widgets.
- `test_scripts/test_m3_ui_defaults_followup.py`: generated 23-page PDFs, real MVC,
  focus regression tests, dialog validation and cancellation.
- `test_scripts/test_page_controls.py`: update private-method driving only.
- `TODOS.md`, `docs/to_Update.md`, `docs/PITFALLS.md` and index: requested status.
- Architecture unchanged; Controller, Model and straighten remain outside scope.

## Decisions
- Rotation retains its all-pages default. Resolve ribbon tabs by label.
- Keep existing viewport route; extend Home/End routing without broad shortcuts
  that could steal input focus or change PageUp/PageDown implementation.
- Dialog results include custom text; use existing strict parser for validation.
- Run artifacts stay outside tracked files. No commits or git staging.

## Running log
- Confirmed original code routes navigation only through viewport and opens a
  second QInputDialog for custom ranges. Qt ribbon bubbling needs runtime evidence.
- Red command: `.venv\Scripts\python.exe -m pytest test_scripts/test_m3_ui_defaults_followup.py -q --tb=short`
  (output captured in temporary `m3-ui-red.txt`).
  ```text
  test_end_home_via_graphics_view_focus: assert 0 == 22
  test_end_home_via_ribbon_tab_bar_focus: assert 0 == 22
  test_ribbon_tab_follows_document_presence: 檔案 != 常用
  test_delete_dialog_defaults_to_current_page: 全部 != 目前頁
  test_custom_scope_inline_input_validates_before_ok[delete/rotate]:
    AssertionError: custom range input must live in the original dialog
  6 failed, 6 passed in 6.21s
  ```
  PageUp/PageDown and key ownership regression checks passed before implementation.
- Implemented Home/End filtering on QGraphicsView and parent handling restricted
  to ribbon focus. QTabBar bubbles these keys; no change to its Ctrl+Tab behavior
  or to PageUp/PageDown implementation. Ribbon transition logic is only in
  set_document_tabs; range widgets share the strict parser and explicit defaults.
- Focused results: new file 12 passed (then removed redundant disconnect warning);
  page_controls 6 passed; shell_tab_ux 19 passed; multi_tab_plan 118 passed, 1 skipped.
- Supervised app run: actual initial focus `_NoCtrlTabTabBar`; immediate End,
  canvas Home/End, ribbon Home/End, PageDown/PageUp and delete/rotate scope default,
  hidden/invalid/valid input states passed. Screenshots captured outside repository.
- Driver dead end: synthetic Ctrl+W sent directly to the main window did not close
  the tab after modal dialogs. Retried using the visible tab close button; no
  production change outside the four requested items.
- Environment: shell creation was temporarily denied while an earlier foreground
  job was active (CreateProcessAsUserW failed: 5); a retry after its exit worked.
- Second supervised run: visible tab close succeeded and empty ribbon was 檔案;
  external supervisor ended driver with exit 124 after file-picker automation
  stalled. Driver now supplies deterministic file-selection I/O but still drives
  the real Open QAction. The picker itself is outside the requested fixes.
- Final app driver: `scripts/verify_supervise.py --stall 120 --ceiling 900 --
  _evidence_pilot/INGEST/m3-ui-defaults/verify_driver.py` exited 0 after 4.8s.
  Verified initial ribbon focus, no-click End, canvas/ribbon Home/End, native
  PgDn/PgUp, default delete/rotate scopes, inline invalid/valid inputs and focus,
  visible close -> 檔案, real Open action -> 常用. Captured screenshots 01 through
  08 (plus invalid/valid/default dialog crops) in a temporary directory; inspected
  screenshots of invalid input, valid rotation, empty shell and reopened shell.
- Final new-file rerun: 12 passed, no disconnect warnings. Existing targeted files:
  page_controls 6 passed; shell_tab_ux 19 passed; multi_tab_plan 118 passed, 1 skipped.
- Independent plan-code-reviewer: no confirmed correctness findings. Status/index
  items from review have been completed; final suite and pre-push evidence pending.
- Fence: existing ARCHITECTURE navigation wording mentions viewport only; left
  unchanged per owner. Inline-editor regression uses a QLineEdit assigned to the
  editor field, rather than the real scene editor; shared editor guards unchanged.
  Rotation default remains 全部. Native picker and synthetic Ctrl+W automation
  limitations remain outside scope; no production changes made for those paths.
- Whole-suite command: `.venv\Scripts\python.exe scripts/run_suite.py`, exit 1,
  9769 passed, 26 failed, 203 skipped, 0 xfailed/errors/hung/crashed, 1 rc5-ok,
  1332.6 seconds. JUnit: `.run_suite/20261105T002904Z/junit.xml`.
- Failure classification from full JUnit messages and existing test source:
  core_interaction_audit 1 + no_jump_editor_geometry 13 + ui_real_corpus 2 require
  absent corpus files; replay_fast_path 1 sees only 1 replayed page, expects >20.
  security_single_instance_isolation 1 + single_instance_forwarding 8 fail at
  QLocalServer listener startup before the changed navigation/dialog behavior.
- Independent QCoreApplication/QLocalServer probe (no View import): listen=False,
  UnknownSocketError, `QLocalServerPrivate::addListener: 存取被拒。`.
  No permission workaround attempted. No baseline checkout/full-suite rerun.
- `.venv\Scripts\python.exe scripts/hooks/pre_push_checks.py`: exit 0; full-tree
  ruff clean, mypy 82 files clean, 4 import contracts kept, threading check clean.
- `git diff --check`: exit 0; tracked edited files retain CRLF, diff is localized.
- Acceptance remains partial; no claim of a green whole suite. Plan intentionally
  remains outside archive until the missing corpus and socket environment allow
  final suite acceptance. No commits, staging, pushes, merges or PRs.
- Final independent review: VERDICT ship for the four scoped UI changes, no
  confirmed findings; explicitly retains partial whole-suite acceptance, no
  measured baseline delta, deterministic picker I/O and editor-evidence limits.
