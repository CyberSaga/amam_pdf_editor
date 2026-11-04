# Suggested product-layer changes (case ecc-1 / mc_malformed_pairing)

- Primary variable this run: `DFKaiShu_Type0_IdentityH_cjk_ideograph_name_to_tu_vs_HVAC_PMingLiU_mc`
- Keep fail-closed; do not disable `mc_malformed_pairing` globally.
- Use this show fingerprint + live probe detail as a regression fixture.
- Case 2: MC gate locality across distinct shows (seq 11 vs 16) with ideograph-class edits.
- Case 8: fingerprint stable spelling under nonzero TJ compensation paths.
- ECC DFKaiShu (標楷體) Type0 Identity-H vs prior HVAC PMingLiU/Arial/JhengHei pilots.
- Experiment splice success is NOT product acceptance while prepare still rejects.
