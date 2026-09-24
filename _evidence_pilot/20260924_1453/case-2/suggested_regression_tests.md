# Regression tests (case 2)

1. Pin HVAC sha256 `9da93de982145c46af0d34a978b4bbaa1167f0937327dedb44ecad4d50fca0a2`, page_index=4, seq=16.
2. Assert prepare reason == `mc_malformed_pairing` until an intentional gate change.
3. Primary variable under test: `cjk_ideograph_tu_to_biao_vs_case1_digit_only`.
4. After any gate change: same font_resource/Tm/CTM/hscale/origin; neighbors unmoved;
   outside-halo pixels 0 at zoom=2; reopen decode equals replacement; no scale-to-bbox.
5. Negative: font-swap / insert_text rebuild must still fail fidelity asserts.
