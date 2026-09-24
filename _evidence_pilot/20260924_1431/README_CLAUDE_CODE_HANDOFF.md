# Claude Code handoff package (NOT handed off — local prep only)

Package: `_evidence_pilot\20260924_1431`
Timezone stamp: 20260924_1431 Asia/Taipei (UTC+8)

## Chosen pilots
- case_id 1 → mc_malformed_pairing (HVAC page_index=4 seq=11)
- case_id 7 → verification_failed (HVAC page_index=5 seq=60)
- case_id 10 → trm_reflected (HVAC page_index=6 seq=5)

Case IDs are the explicit `case` integers from `output/pdf/manual-font-study/results.json`
and `scripts/experiment_hvac_font_edits.py` (enumerate CASES from 1).

## Verified hashes
- HVAC: `9da93de982145c46af0d34a978b4bbaa1167f0937327dedb44ecad4d50fca0a2`
- ECC (verified, not piloted edits): `0f75dd10ed77214c5cf159d40f909cd402231761886cb0ed3821368ac0ab1853`

## Constraints honored
- No product source modifications
- Original PDFs untouched; candidates only under this folder
- Vector/outline PDFs classified out of true-text scope
- No cloud upload of PDF binaries
- accepted_for_code not claimed (engine still rejects; UI unverified)

## Next
See each case-*/suggested_product_layer_changes.md and cases.json statuses.
