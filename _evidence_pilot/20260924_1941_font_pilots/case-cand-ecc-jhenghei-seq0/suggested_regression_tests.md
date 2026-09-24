# Regression tests (cand-ecc-jhenghei-seq0)

1. Pin source sha256 0f75dd10ed77214c5cf159d40f909cd402231761886cb0ed3821368ac0ab1853, page_index=0, seq=0, font MicrosoftJhengHeiRegular.
2. Record prepare reason from live_engine_probe.json until intentional gate change.
3. Primary variable: ecc_jhenghei_plan_label.
4. After any gate change: same font_resource/Tm/CTM/hscale/origin; neighbors unmoved;
   outside-halo pixels 0 at zoom=2; reopen decode equals replacement; no scale-to-bbox.
5. Negative: font-swap / insert_text rebuild must still fail fidelity asserts.
