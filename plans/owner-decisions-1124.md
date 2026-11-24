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
