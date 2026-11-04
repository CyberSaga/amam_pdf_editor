# Retire the legacy engine option (TODOS item "retire the legacy engine option")

## Current state and next step (keep at most 40 lines)

- Slice 1 (engine option: `legacy`, `shadow`, plus `TEXT_COMMIT_TELEMETRY`): DONE in a lane worktree (uncommitted).
- Slice 2 (`TEXT_COMMIT_PREVIEW=legacy`, ruling O3): DONE in the lane (uncommitted), steps 10-16 below. Waiting for
  the merge and the whole-suite run (`scripts/run_suite.py`), which is not run in the lane.
- Slice 2 done: red pins shown red (settings 2, shipped_defaults 1), `TextCommitSettings.preview` accepts only
  `"plan"` (ValueError; stored `legacy` warns and runs plan), `activate()` always `require_token(True)`, the
  controller's early return deleted, `test_scripts/preview_levers.py::tokenless_view` (run AFTER `activate()`),
  the section-3 sites converted (finalize_policy, finalize_by_result `_App(tokenless=)`, small_defects,
  rebuild_action, mouse_gestures `_gui_session(tokenless=)`, add_text_intent, plan_preview_no_css,
  apply_by_token, preview_contract (1 test deleted), multi_tab `mvc_rebuild`, no_jump 3 sites), P8/P12/P15,
  ARCHITECTURE (1146, 1199, 2138), PITFALLS (slice-2 paragraph + "A test lever that `activate()` overwrites"),
  TODOS:22 closed (both halves) with the O2 candidate and the follow-ups kept, no_jump SHA re-pinned.
- Done (lane, uncommitted): steps 1-8 of slice 1. Red pins shown red (settings 6, shipped_defaults 2,
  default_engine_ux 2, consent_flow P7 2), conversions green on the old product code (edit_text_helpers: RAN
  caught 12 vacuous Tier 0/1 twins -> FR added in `_neighbour_edit` / `_edge_edit`), product changes P1-P3,
  P5-P11, P13, P16 applied, every touched test file green after them, grep gates clean, mypy + ruff clean,
  `test_no_jump_editor_geometry.py` re-pinned (`ecdfb0e5…`, LF bytes), docs + TODOS written.
- Next: merge the lane, then `scripts/run_suite.py` (whole suite) and `python scripts/build_pitfalls_index.py`
  and the code-graph re-index (both deliberately not run in the lane); owner review of the provisional
  decisions (log below, slices 1 and 2). Then `git mv` this plan to `plans/archive/`.
- Whole-suite gate (`scripts/run_suite.py`) runs once after the lane merges; not run in the lane.

## Goal

Owner 2026-11-02: 「我早就不想要 legacy 了」. `TextCommitSettings(engine="legacy")`, `TEXT_COMMIT_ENGINE=legacy|shadow`
and `TEXT_COMMIT_TELEMETRY` are operator escape hatches that reach `_apply_redact_insert` without the consent gate,
without `rebuild_paint` (F17-COL), without the glyph-loss acknowledgement (F11-UNI-1) and without the signed/widget
hard reject. Retire the option; keep the consented rebuild (改用重建文字, `_apply_redact_insert` behind
`allow_rebuild=True` plus an accepting `confirm_fallback`).

## Decisions (owner rulings 2026-11-04, all per the inventory recommendations)

| # | Decision | Ruling |
|---|----------|--------|
| O1 | Go / no-go for slice 1 (`legacy` and `shadow`) | Go |
| O2 | No route remains for editing text on a page with real form widgets or in a signed document | Accepted; the signed/widget hard reject becomes unconditional (P9). A future feature is a TODOS candidate (「未來再新增功能處理」) |
| O3 | `TEXT_COMMIT_PREVIEW=legacy` | Retire in a separate slice 2; keep the view-level flag `set_text_plan_preview_required` as the test lever |
| O4 | Shadow engine and `TEXT_COMMIT_TELEMETRY` | Retire both with legacy in slice 1 |
| O5 | A stored `TEXT_COMMIT_ENGINE=legacy|shadow` | Log a warning naming the retired value, fall back to tiered; never crash at launch |
| O6 | `TextCommitSettings.engine` | Keep the field, accept only `"tiered"`; the constructor raises `ValueError` otherwise |

Kept on purpose: `CommitTier.TIER2_LEGACY`, `legacy_commit_outcome()`, `is_real_fallback_commit`'s `!= ("legacy",)`
clause (DTO-level tests still build bare chains); P7 closes the only product path that could record a bare chain.

## Mechanics

- **FR** (`force_rebuild`): `test_scripts/rebuild_forcing.py::force_rebuild` monkeypatches
  `model.pdf_text_edit._attempt_tiered_commit` to return `(None, RejectReason.MULTI_SPAN_TARGET)`, so an ordinary
  fixture takes the real consented path (tiered refusal, consent, `rebuild_paint`, glyph-loss gate,
  `_apply_redact_insert`, `_verify_rebuild_edit`). The consent still has to come from the request
  (`allow_rebuild=True` plus an accepting `confirm_fallback`).
- **RAN** (`assert_rebuild_ran(model)`): `last_commit_outcome.tier is CommitTier.TIER2_LEGACY` and
  `fallback_chain[0].startswith("tier0:")`. Every swapped edit test asserts it, so a Tier 0/1 commit cannot make it
  pass vacuously (PITFALLS "Flipping a behavior policy makes tests that depended on the old behavior pass
  vacuously"). Never loosen RAN; add FR.

## Inventory (copied from the 2026-11-04 read-only inventory; row numbers are used in the log)

Categories: PIN (pins legacy-only behavior), CTRL (uses the option only to force the rebuild), OPT (tests the option
itself), OTHER (engine irrelevant), PREV (depends only on slice 2), PROD (product code, scripts, docs).

### Test rows (engine slice)

| # | file:line | proposal |
|---|-----------|----------|
| 1 | test_edit_text_helpers.py:35 `_accept_rebuild` docstring | keep |
| 2 | test_edit_text_helpers.py:2051 f15vm2 rtl rebuild right edge | default + FR + RAN |
| 3 | test_edit_text_helpers.py:2114 f15vm2 leading blank line | default + FR + RAN |
| 4-6, 8, 9 | test_edit_text_helpers.py:2218, 2263, 2310, 2362, 2385 | drop kwarg |
| 7 | test_edit_text_helpers.py:2337 f16 rtl order rebuild | default + FR + RAN |
| 10 | test_edit_text_helpers.py:4010 `_neighbour_edit` | remove the engine arg; RAN inside for SUCCESS; FR if needed |
| 11, 12, 14, 16, 17, 19-21, 23, 24 | test_edit_text_helpers.py parametrized `["legacy","tiered"]` | delete the legacy value; RAN on the tiered twin |
| 13, 18, 32, 33 | test_edit_text_helpers.py:4185, 4552, 5458, 5495 | drop kwarg |
| 15, 22, 38, 42 | helpers `_diag_edit`, `_edge_edit`, `_dg_drag`, `_dg_drag_free_inplace` | drop the engine arg |
| 25-31 | test_edit_text_helpers.py:4964-5287 f14vm2 / f15vm2 fast180 / f16_2 | default (+ FR where Tier 0/1 could admit) + RAN |
| 34-37, 39-44 | test_edit_text_helpers.py f13vf4b / s17 parametrized | delete the legacy value |
| 45 | degrade_visibility docstring marker | keep |
| 46, 47 | degrade_visibility:607, 727 | delete (PIN) |
| 48, 50, 51 | degrade_visibility:980, 1109, 1152 | default settings |
| 49 | degrade_visibility:1010-1021 docstring | reword |
| 52 | degrade_visibility:1183 dead reflow hook | `_tj_array_stream` + consent + RAN |
| 53 | refusal_messages:133 `_launched(engine=)` | remove the param |
| 54 | refusal_messages:502 `_legacy_history` | rewrite as `_consented_history`; 517 injects at `cmd.execute` |
| 55, 60 | refusal_messages:859, 1200 | drop `engine="legacy"` |
| 56-59 | refusal_messages:1064-1146 | `PDFModel()` / drop kwarg |
| 61, 62 | overlap_textbox_edit:360, 396 | default + FR |
| 63-65 | overlap_textbox_edit:445, 514, 836 | `PDFModel()` |
| 66-70 | settings:33, 44-53, 56, 77, 109 | retirement pins / delete engine-derived preview rows / drop ENGINE+TELEMETRY |
| 71 | settings:129 | keep |
| 72 | settings:151 | sample `strict=True` |
| 73 | consent_flow:33 docstring | trim |
| 74 | consent_flow:325 | delete (PIN) |
| 75 | no_silent_legacy:819-840 | delete `_LEGACY` + 3 tests (and the fixture's `_notify_legacy_baseline_degrade` patch) |
| 76 | no_silent_legacy:426 docstring | reword as history |
| 77, 78 | hyphen_wrap `_ENGINES`, 328 | drop legacy; RAN in `_edit`; FR for 328 |
| 79, 80 | object_manipulation:1086, 10 positional `"legacy"` | drop legacy; per-test FR + RAN |
| 81 | characterization docstring | reword |
| 82 | source_show_commit:619 | rewrite: default + FR + consent; rename |
| 83 | source_show_commit:742 | default + FR + consent + RAN; rename |
| 84 | multi_tab_plan:284 `mvc_legacy` | `mvc_rebuild`: shipped settings, confirm patched, `allow_rebuild=True`, FR, RAN |
| 85 | no_jump_editor_geometry:1411 | commit through the rebuild with consent; SHA re-pin |
| 86 | paragraph_multi_font_target:247 | default + consent; RAN; drop the settings swap |
| 87 | rtl_edit_growth:56 `_model()` | `TextCommitSettings()`; RAN / FR where needed |
| 88 | default_engine_ux:388 | delete; replace with "no setting bypasses SIGNED_OR_WIDGET" |
| 89 | default_engine_ux:534 | delete the legacy value; rename |
| 90 | maintenance:72 | fallback `TextCommitSettings()` |
| 91-95 | shadow_mode 95-188 | delete; rename the file |
| 96 | page_rotation:148 `_legacy_model()` | `_rebuild_*`; consent in `_replace_hit`; FR for no_rect modes; RAN |
| 97 | shipped_defaults:28 | keep scrub; reword docstring |
| 98 | shipped_defaults:238 | retirement pin at app level |
| 99-102 | finalize_by_result:127, ui_real_corpus, decision_chain, intent, encrypted_safety | no change / reword |
| 103-106 | PREV rows (slice 2) | untouched in slice 1 |

### Product rows

| # | site | proposal |
|---|------|----------|
| P1 | dto `_ENGINE_VALUES`, `_PREVIEW_AUTO`, `default_preview_for`, `_TELEMETRY_VALUES` | engine `("tiered",)` + `_RETIRED_ENGINES`; preview default constant `"plan"`; telemetry gone |
| P2 | dto fields / docstring / `__post_init__` / `from_env` | ValueError on non-tiered; telemetry removed, env ignored; retirement docstring |
| P3 | dto `is_real_fallback_commit` | keep the clause; reword the docstring |
| P4 | dto `TIER2_LEGACY`, `legacy_commit_outcome` | keep |
| P5 | pdf_text_edit `_shadow_classify_edit` + branch | delete |
| P6 | pdf_text_edit tiered arm | unconditional (dedent) |
| P7 | pdf_text_edit rebuild outcome chain | record `pending_chain` unconditionally |
| P8 | pdf_text_edit:906 docstring | reword |
| P9 | pdf_model signed/widget hard reject | unconditional |
| P10 | controller T16-1 baseline branch | delete the three methods and both elif sites |
| P11 | controller cross-page consent comment | reword as history |
| P13 | edit_commands redo comments | reword; re-run leg is mock-only (follow-up) |
| P16 | scripts/benchmark_engine_default_ab.py | delete (git keeps history) |
| P19 | ARCHITECTURE, 架構.txt, PITFALLS | history + new state; new PITFALLS entry |

Consciously dropped behaviors: D1 widget/signature escape hatch (O2); D2 the T16-1 legacy-baseline notice and bare
`("legacy",)` chain; D3 "the legacy engine never asks"; D4 legacy variants of the cross-page move gate (same checks
run on the default); D5 the redo that re-runs `model.edit_text` for a real commit; D6 shadow logging and the
telemetry gate; D7 the preview-follows-engine coupling; D8 the A/B benchmark script.

## Log

- 2026-11-04: plan created in the lane.
- 2026-11-04 (lane): slice 1 implemented. Provisional decisions (owner reviews):
  - `test_text_commit_shadow_mode.py` renamed to `test_text_commit_tiered_integration.py` by a plain file
    rename (lane rules forbid index operations); git sees delete + new file.
  - `scripts/benchmark_engine_default_ab.py` deleted rather than moved to `docs/history/` (it cannot run; git
    keeps it).
  - `TEXT_COMMIT_TELEMETRY` ignored silently (the `TEXT_COMMIT_CONFIRM_DEGRADE` precedent), no warning.
  - GUI tests whose subject is the rebuild (`test_multi_tab_plan.py::mvc_rebuild`, no_jump reopen test) inject
    `allow_rebuild=True` at `controller._commit_text_edit` instead of clicking 改用重建文字 each cycle, keep
    `preview="legacy"` (slice 2 moves them to the view flag), and assert RAN (multi_tab: recorded, checked at
    fixture teardown because a Qt slot swallows assertions).
  - Page-rotation, multi-tab and other test names kept (only helpers renamed) so PITFALLS / TODOS `File:`
    references stay valid; renamed: refusal_messages `test_redo_that_raises_a_coded_refusal_...` (PITFALLS
    reference updated), source_show_commit two tests, default_engine_ux row 89.
  - Where the legacy half of a `["legacy","tiered"]` pair was not a plain duplicate, the fixture keeps both
    paths (object_manipulation `path=["tiered","rebuild"]`); elsewhere the legacy value was deleted and the
    helper forces the rebuild when RAN showed the tiered twin committing at Tier 0/1.
- 2026-11-04 (lane): slice 2 implemented (steps 10-16). Provisional decisions (owner reviews):
  - **Inventory correction (P12).** Deleting the controller's `preview != "plan"` early return was not enough: the
    View installed the editor's plan-preview request hook regardless of its token gate, and that early return was
    the only thing dropping a tokenless View's requests. Without a View-side fix the preview worker ran on a
    tokenless editor (rebuild button shown before Apply; `test_no_jump_editor_geometry.py` crashed the process,
    0xC0000409, near the end of the file). Fix: `create_text_editor` installs the hook only
    `if self._plan_preview_applies(intent)` (still the single read of the flag; the guard test passes). Red pin:
    `test_tokenless_view_emits_no_plan_preview_request`.
  - `test_refused_apply_keeps_the_editor_the_input_and_the_pdf` (tokenless): the assertion "the kept editor
    re-requests a preview" became "a tokenless View sends no request" (generation still bumps). The plan-mode
    re-request stays pinned by the plan-mode tests in the same file (632, 656) and `apply_by_token`.
  - `test_controller_ignores_requests_when_preview_flag_is_legacy` (preview_contract) deleted: the subject
    (the Controller dropping requests by setting) no longer exists; the settings retirement pins and the new View
    pin replace it.
  - `launch(...)`/`_gui_session`/`gui` fixtures take `tokenless=`/`"tokenless"` instead of `preview=`/`"legacy"`;
    parametrized ids `["legacy","plan"]` became `["tokenless","plan"]`. Test ids such as `legacy_refused` in
    finalize_policy and the names `gui_legacy`, `test_legacy_preview_mode_keeps_apply_enabled` were kept to
    avoid churn in references (one renamed: `test_tokenless_commit_refusal_offers_the_rebuild`).
  - `multi_tab` `mvc_rebuild` wraps `controller.activate` (the Controller activates lazily inside the tests) so the
    token gate is cleared after every activation.
  - `PDFController.activate()` calls `require_token(True)` unconditionally; the `getattr(... "set_text_plan_preview_required")`
    guard for minimal test views stays.
  - ARCHITECTURE: lines 827/1424 (2026-07 history) left as written; 1146, 1199, 2138 updated.
