# Regression tests (cand-hvac-trebuchet-m5)

1. Pin source sha256 9da93de982145c46af0d34a978b4bbaa1167f0937327dedb44ecad4d50fca0a2, page_index=3, seq=53, font TrebuchetMS.
2. Record prepare reason from live_engine_probe.json until intentional gate change.
3. Primary variable: latin_specialty_trebuchet_cid.
4. After any gate change: same font_resource/Tm/CTM/hscale/origin; neighbors unmoved;
   outside-halo pixels 0 at zoom=2; reopen decode equals replacement; no scale-to-bbox.
5. Negative: font-swap / insert_text rebuild must still fail fidelity asserts.
