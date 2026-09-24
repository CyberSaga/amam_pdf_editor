# Suggested product-layer changes (case 2 / mc_malformed_pairing)

- Primary variable this run: `cjk_ideograph_tu_to_biao_vs_case1_digit_only`
- Keep fail-closed; do not disable `mc_malformed_pairing` globally.
- Use this show fingerprint + live probe detail as a regression fixture.
- Case 2: MC gate locality across distinct shows (seq 11 vs 16) with ideograph-class edits.
- Case 8: fingerprint stable spelling under nonzero TJ compensation paths.
- Case 10 deepen: admit intentional reflected TRM only with tests that preserve negative det under length-changing replacements.
- Experiment splice success is NOT product acceptance while prepare still rejects.
