# Suggested product-layer changes (case 10 / trm_reflected)

- Keep fail-closed; do not disable `trm_reflected` globally.
- Use this show fingerprint + live probe detail as a regression fixture.
- Case 1: split true malformed MC from valid q/Q-crossing OC before widening admission.
- Case 7: stabilize scratch fingerprint spelling (live vs tobytes) before trusting prepare.
- Case 10: admit intentional reflected TRM only with explicit tests (preserve negative det).
- Experiment splice success is NOT product acceptance while prepare still rejects.
