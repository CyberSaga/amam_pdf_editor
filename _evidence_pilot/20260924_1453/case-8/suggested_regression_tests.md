# Regression tests (case 8)

1. Pin HVAC sha256 `9da93de982145c46af0d34a978b4bbaa1167f0937327dedb44ecad4d50fca0a2`, page_index=5, seq=58.
2. Assert prepare reason == `verification_failed` until an intentional gate change.
3. Primary variable under test: `nonzero_tj_compensation_Aban_to_Bban_vs_case7_date_digit_kern0`.
4. After any gate change: same font_resource/Tm/CTM/hscale/origin; neighbors unmoved;
   outside-halo pixels 0 at zoom=2; reopen decode equals replacement; no scale-to-bbox.
5. Negative: font-swap / insert_text rebuild must still fail fidelity asserts.
