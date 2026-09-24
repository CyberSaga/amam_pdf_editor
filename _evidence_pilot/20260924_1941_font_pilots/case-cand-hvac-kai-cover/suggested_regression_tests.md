# Regression tests (cand-hvac-kai-cover)

1. Pin source sha256 9da93de982145c46af0d34a978b4bbaa1167f0937327dedb44ecad4d50fca0a2, page_index=0, seq=7, font DFKaiShu-SB-Estd-BF.
2. Record prepare reason from live_engine_probe.json until intentional gate change.
3. Primary variable: hvac_kai_cover_vs_ecc_titleblock.
4. After any gate change: same font_resource/Tm/CTM/hscale/origin; neighbors unmoved;
   outside-halo pixels 0 at zoom=2; reopen decode equals replacement; no scale-to-bbox.
5. Negative: font-swap / insert_text rebuild must still fail fidelity asserts.
