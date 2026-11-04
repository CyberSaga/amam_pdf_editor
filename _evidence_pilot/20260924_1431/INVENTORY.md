# Inventory (this pilot)

## HVAC 10 (true-text Type0) — scripts/experiment_hvac_font_edits.py CASES
| case | page_index | seq | signature (engine max_tier=1) | piloted |
|---:|---:|---:|---|---|
| 1 | 4 | 11 | mc_malformed_pairing | YES |
| 2 | 4 | 16 | mc_malformed_pairing | no |
| 3 | 4 | 6 | mc_malformed_pairing | no |
| 4 | 4 | 7 | mc_malformed_pairing | no |
| 5 | 4 | 18 | mc_malformed_pairing | no |
| 6 | 4 | 26 | mc_malformed_pairing | no |
| 7 | 5 | 60 | verification_failed | YES |
| 8 | 5 | 58 | verification_failed | no |
| 9 | 6 | 7 | verification_failed | no |
| 10 | 6 | 5 | trm_reflected | YES |

## ECC 4 (true-text Type0 DFKaiShu) — output/pdf/cad-font-study/results.json
| # | seq | before -> after | historical engine note (conversation export) |
|---:|---:|---|---|
| 1 | 31 | 專案名稱 -> 專案圖名 | mc_malformed_pairing |
| 2 | 38 | 平面配置圖 -> 機房配置圖 | mc_malformed_pairing |
| 3 | 57 | 113.05.03 -> 113.05.05 | verification_failed |
| 4 | 60 | [ECC_DWG] -> ECC-3 | verification_failed |

ECC not selected this run (HVAC already supplied one representative per signature with explicit case integers).

## Out of true-text success scope (classify/report only)
- [VECTOR_CHB_PDF] — vector drawings only (method source_vector_translation); no fonts/traces
- [VECTOR_AIRPORT_PDF] — vector drawings only

These must NOT be counted as true-text success.
