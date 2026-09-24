# Font inventory (20260924_1612 Asia/Taipei)

Scan of `test_files` PDFs for font resources used by actual text shows.
Classification: common/default-ish · non-default CJK (標楷體/DFKaiShu/KaiTi) · other specialty.
Embedding flag from MuPDF `get_fonts(full=True)` (0 often still means subset embedded via descendant — treat as presence of font resource, not OS fallback proof).
ToUnicode / subtype from xref object text.

Verified source hashes:
- HVAC: `9da93de982145c46af0d34a978b4bbaa1167f0937327dedb44ecad4d50fca0a2`
- ECC: `0f75dd10ed77214c5cf159d40f909cd402231761886cb0ed3821368ac0ab1853`
- CHB: `1580cbc98bc4506d6c8ea73b732eb91267468f4311a4ed21e943ac4f89c2024d`
- [AIRPORT_CODE]: `c994e9f888588a6684cd64bdff8e4b0ea6c85fc46eed3b4d0c8cd8120c0494f7`

## [ECC_DWG].pdf (true-text Type0 — primary target this batch)

| BaseFont | subtype | encoding | ToUnicode | class | notes |
|---|---|---|---|---|---|
| DFKaiShu-SB-Estd-BF | Type0 | Identity-H | yes | **non-default CJK Kai (標楷體)** | F2 xref 72; title-block CJK + digits; 32 shows |
| MicrosoftJhengHeiRegular | Type0 | Identity-H | yes | specialty CJK sans | F1 xref 13; plan labels e.g. 丁梯; 30 shows |

Documented true-text CAD edits (`output/pdf/cad-font-study/results.json` + `scripts/experiment_cad_font_edits.py` TEXT_CASES) all use **DFKaiShu-SB-Estd-BF**:
| inventory # | seq | before → after | historical engine note |
|---:|---:|---|---|
| ecc-1 | 31 | 專案名稱 → 專案圖名 | mc_malformed_pairing |
| ecc-2 | 38 | 平面配置圖 → 機房配置圖 | mc_malformed_pairing |
| ecc-3 | 57 | 113.05.03 → 113.05.05 | verification_failed |
| ecc-4 | 60 | [ECC_DWG] → ECC-3 | verification_failed (shorter; TJ −500) |

Neighbor note for ecc-4: seq 58 圖號 / 59 修訂版 / 61 頁碼 sit in same title-block column as [ECC_DWG]; length change risks column alignment — prefer ecc-3 for vf representative.

## [HVAC_DWG_PDF] (true-text; prior pilots used PMingLiU / Arial / JhengHei)

Dominant faces (Type0 Identity-H + ToUnicode unless noted): PMingLiU, ArialMT, MicrosoftJhengHeiRegular, **DFKaiShu-SB-Estd-BF**, SimSun, TrebuchetMS, MicrosoftYaHei-Bold (+ subset prefixes on early pages).
Prior evidence cases 1/2/7/8/10: PMingLiU or ArialMT or JhengHei — **not** DFKaiShu. Do **not** re-run identical HVAC mutations this batch. HVAC DFKaiShu shows exist but lack explicit numbered CASES entries for Kai — not invented here.

## [VECTOR_CHB_PDF] — vector only
font_resources: **[]**. Out of true-text success scope (classify only).

## [AIRPORT_CODE] [AIRPORT_DWG_REV].pdf — vector only
font_resources: **[]**. Out of true-text success scope.

## Other test PDFs (not selected — no explicit edit case_ids)

| file | notable fonts | why not piloted |
|---|---|---|
| 01_報告書.pdf | MingLiU, **DFKaiShu** Type0 Identity-H TU, Arial, Times | no documented TEXT_CASES / case_id |
| Awareness.pdf | Europa / Canela / IvyPresto / ACaslon (specialty Latin Type1) | no CJK true-text cases documented |
| test-horizontal-texts.pdf | Aptos, PMingLiU | default-ish; no case_ids |
| test-vertical-texts.pdf | Aptos | no case_ids |
| test-complexed-layout.pdf | Type3 unnamed, Consolas, IBMPlexMono, ArialUnicodeMS | specialty but no edit cases |

## Classification summary (non-default of interest)

| font family | where | true-text? |
|---|---|---|
| **DFKaiShu-SB-Estd-BF (標楷體)** | ECC (primary), HVAC (present), 01_報告書 | ECC yes (documented) |
| MicrosoftJhengHeiRegular | ECC F1, HVAC | ECC yes but no documented edit seq; HVAC case7 already piloted |
| PMingLiU / ArialMT | HVAC heavy | prior pilots — out of this batch |
| (none) | CHB / [AIRPORT_CODE] | vector only |

Raw machine dump: `_evidence_pilot/_tmp_font_inventory.json` (scratch; authoritative prose is this file).
