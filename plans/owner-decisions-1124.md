# Owner decisions 2026-11-24 (recorded, not executed)

Source: owner message after the 11-24 context review. Owner said: record these, do not execute.

## Decisions

1. Quit gate round 10 P1s (4): ACCEPTED, not fixed. Owner: "Opus + Astra could not fix them, so accept."
   Refs: plans/cad-m0-h23-review.md Round 10 (lines 180-186).
   Open item: the closing trap check (QMessageBox/QDialog.exec trap, blocking-call trap, launch-time fault injection) was NOT built; owner did not ask for it.

2. quit ceiling: CONFIRMED, 30 s (QUIT_CEILING_MS = 30000), per plans/worker-lifetime-quit-gate.md.

3. B2 P2 list (Astra round 3): record now; after B4 completes, handle (a), (e), (g) as one numeric threshold rule; handle the rest with the outcome check described in the handoff.
   Refs: plans/cad-vector-object-editing-handoff.md line 560.

4. B2 provisional decisions: ALL ADOPTED.
   Note: the handoff text gives 16 items (B2 build, line 527) + 8 items (review fixes). The owner's "31" does not reconcile with the 24 I could read; the adoption covers whatever the handoff lists. Count to be reconciled before the record is closed.

5. fill topology schema addition (segments.subpath): DESIGN BY GPT-6.2-Astra.

6. CLIPPED definition: COMPUTE AND TEST by Astra (the definition question: "any clip" vs "clip narrower than page box"; scanner cannot compare geometry today).

7. H5 (GUI heartbeat 140 ms vs 100 ms): DEFERRED to card B.

8. D21 resolver placement: DECIDE by GPT-6.2-Astra.


## Open for a stronger model (2026-11-24)
- Owner: "closing traps must be built" (reverses decision 1 for the trap check only).
- Open choice, not yet answered: how the suite treats the 4 accepted round-10 P1s once the traps exist.
  (a) strict xfail with reason citing cad-m0-h23-review.md Round 10 (needs waiver of the 11-02 "0 xfail" policy)
  (b) leave red (CI windows leg blocks)
  (c) local_only (not gating CI)
- Recommended by Haiku: (a), with the waiver written down. Not decided by the owner.
- Design still open: where the traps sit (child QMessageBox/QDialog.exec trap, GUI blocking-call trap across the whole drain, launch-time fault injection at every start_owned / start_owned_child site).
- Rule: red test first, show failure, then implement. Nothing built yet.

## Not decided here
- Push: already done (origin at fc278a29, 11-24 00:37). No further push requested.
- B4 (accelerator F): not started; owner did not say when.

## Owner decisions 2026-11-25 (recorded; B4 follow-ups and traps NOT executed)
1. Commit the B4 files and make them readable for Astra: DONE in this step (commit + push, see git log).
2. B4: add the card's mask stage (strings, dictionaries, text objects, BDC/EMC, W, Do, colour-space names) so F covers real drawings. Memory work toward 400 MiB is DEFERRED. Not started.
3. Round-10 P1 closing traps: build GREEN with a pinned allowlist of the 4 accepted sites; the trap fails on any NEW site and on a STALE entry (an allowlisted site that stops triggering). No xfail, no waiver of the 11-02 policy. Not started. (Option d.)
4. The full 31 provisional B2 decisions: recorded in plans/b2-provisional-decisions-31.md (16 build + 15 review fixes). Not executed. Item 4 of the 11-24 record is reconciled: 31, not 24.
5. Push: authorised for this commit only.

- 2026-11-25 (owner: 「做 P1 收尾陷阱選項 d」): BUILT `test_scripts/test_drain_traps.py` (5 tests, green). Modal trap + blocking-join trap over a handler table, pinned ACCEPTED allowlist of the 4 accepted round-10 sites (optimize/search/OCR failure modals, handle_app_close sync joins); a NEW site fails, a STALE entry fails, a control run with admission open proves the trap sees modals, a structural check keeps the table complete. Red first: empty allowlist failed naming exactly the 4 sites. No xfail. NOT built: launch-time fault injection at every start_owned/start_owned_child site (round-10 P1s 1 and 2); needs a seam in the registry.
- 2026-11-25 (owner: 「做啟動時注入例外的陷阱」): BUILT `test_scripts/test_launch_fault_traps.py` (4 tests, green, uncommitted). Faults: native start then raise for a thread and a child process (at the registry chokepoint all 13 launch sites share), and a replacement main.run started from a registry entry's alive() inside drain_after_exec's final sweep (subprocess). ACCEPTED = the 3 reproduced round-10 P1 sites; new/stale both fail; 13 launch sites pinned by AST census. No production change, no xfail.

- 2026-11-26 (owner: 「完成 B5 … 直到明早 7 點晨報」, overnight): B5 model wiring built UNCOMMITTED (see TODOS B5 line). Provisional calls to ratify: skipped = non-editable rows the same geometry reaches; supports_move excludes CLIPPED/PAGE_ANCHORED rows; per-page index cache keyed by handle_generation + content_revision. Opus advisor consulted on scoping (rotation order, skipped, 50 ms gate). Real-sample click 25 ms median.
- 2026-11-26 (overnight, provisional, owner to ratify): (1) B6 model commit built from Astra's design (plans/b6-commit-design-astra.md), model only, no controller. (2) digest_table normal form changed: dictionary key order ignored at every level, trailer xref-stream keys skipped; new commit_state.equivalent() ignores container slots, used ONLY to verify a restore and an undo/redo (rule B stays strict). Evidence: 5/5 real files failed a null capture->restore before, 5/5 pass after (PITFALLS entry). (3) Astra-flagged owner decisions still open: H22 "edit retained, verification interrupted" (OCR writer can land during a pumped pass); retained non-scalar dictionary references on a copied stream are refused before allocation. (4) vector_editing_blocked / vector_last_pass_ms live on the session (legacy fallback like secure_save_required). (5) the product delete vs the B1 oracles: 36/60 twin cells pass; the 24 failures are ops (0,) and (9,) = a single-path q..Q state wrapper that D17/the scanner remove whole and the builder's expected() keeps; sent to Astra (scratchpad astra_ap.out).
