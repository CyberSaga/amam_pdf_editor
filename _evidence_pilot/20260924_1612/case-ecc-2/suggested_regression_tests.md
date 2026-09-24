# Regression tests (case ecc-2)

1. Pin ECC sha256 `0f75dd10ed77214c5cf159d40f909cd402231761886cb0ed3821368ac0ab1853`, page_index=0, seq=38.
2. Assert prepare reason == `mc_malformed_pairing` until an intentional gate change.
3. Primary variable under test: `DFKaiShu_Type0_IdentityH_multi_ideograph_pingmian_to_jifang`.
4. After any gate change: same font_resource/Tm/CTM/hscale/origin; neighbors unmoved;
   outside-halo pixels 0 at zoom=2; reopen decode equals replacement; no scale-to-bbox.
5. Negative: font-swap / insert_text rebuild must still fail fidelity asserts.
