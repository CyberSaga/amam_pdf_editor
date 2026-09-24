# Methods + evidence plan (BEFORE UI runs) — 20260924_1959 Asia/Taipei (UTC+8)

## Goal
Fill **product UI-path** Preview / Apply / Undo / Redo evidence for true-text pilots already exercised via engine/splice. Primary variable this round: **UI path** (not new fonts).

## Hard constraints
- No product source modifications
- Isolated PDF copies under `candidates/` only; originals under `test_files/` untouched
- UI evidence must come from product UI path (PDFView `sig_edit_text` / plan-preview request → PDFController → EditTextCommand → TieredCommitEngine), not experiment splice
- If prepare rejects and Apply cannot complete: record honest `ui_blocked` / `ui_fail` with prepare/degraded reason
- No cloud PDF upload; box mirror JSON/MD only
- Do not invent case_ids; reuse explicit ids from prior packages
- Screenshots alone insufficient for `accepted_for_code`

## UI discovery (Step 1)
See `UI_ENTRY.md`.

## Drive method
Official offscreen harness patterned on `test_scripts/test_text_commit_consent_flow.py`:
- `QT_QPA_PLATFORM=offscreen`
- `PDFModel` + `PDFView` + `PDFController.activate()` + `open_pdf`
- Preview: `TextCommitSettings(preview="plan")`; call `PDFController.on_text_edit_plan_preview_request`; wait for coordinator via monkeypatched `view.apply_text_edit_plan_preview`
- Apply: `view.sig_edit_text.emit(EditTextRequest(...))` with `target_span_id` + `target_mode="run"` (required on rotated HVAC pages)
- Settings: `engine=tiered`, `max_tier=1`, `strict=True`, `preview=plan` (strict so legacy fallback cannot masquerade as true-text Apply success)
- Undo/Redo: `controller.undo()` / `controller.redo()` only if Apply committed; else `skipped`

## Case selection (max 4; spanning prior signatures)
| case_id | lineage | expected engine signature | PDF | page | notes |
|---|---|---|---|---:|---|
| 1 | 20260924_1431 | mc_malformed_pairing | HVAC | 4 | numbered HVAC MC |
| 7 | 20260924_1431 | verification_failed | HVAC | 5 | numbered HVAC VF |
| 10 | 20260924_1431 | trm_reflected | HVAC | 6 | UI index splits Buffer+Tank; expect possible UI-resolve divergence |
| ecc-1 | 20260924_1612 | mc_malformed_pairing | ECC | 0 | DFKaiShu optional fourth |

Not run: case 2/8, cand-* font pilots (UI path variable only).

## Hypotheses
- H1: Plan preview via controller reports reject_reason when prepare cannot succeed
- H2: Apply via sig_edit_text + strict+max_tier=1 yields REJECTED_STRICT and zero undo stack when engine refuses
- H3: Undo/Redo skipped when Apply does not commit
- H4: Case 10 may surface a different UI degraded_reason than direct prepare trm_reflected due to span split — both recorded honestly

## Acceptance
`ui_pass` only if preview+apply+undo+redo all verified on product path.
`accepted_for_code` remains false unless all brief gates hold (not expected this round).
