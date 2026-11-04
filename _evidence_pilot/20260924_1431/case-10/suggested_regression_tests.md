# Regression tests (case 10)

1. Pin HVAC sha256 `9da93de982145c46af0d34a978b4bbaa1167f0937327dedb44ecad4d50fca0a2`, page_index=6, seq=5.
2. Assert prepare reason == `trm_reflected` until an intentional gate change.
3. After any gate change: same font_resource/Tm/CTM/hscale/origin; neighbors unmoved;
   outside-halo pixels 0 at zoom=2; reopen decode equals replacement; no scale-to-bbox.
4. Negative: font-swap / insert_text rebuild must still fail fidelity asserts.
