# Methods + evidence plan (BEFORE edits) — 20260924_1612 Asia/Taipei (UTC+8)

## Goal
Honest evidence on **標楷體 (DFKaiShu-SB-Estd-BF)** and non-default true-text fonts vs prior HVAC PMingLiU/Arial pilots. No product source changes. Isolated copies only. No PDF upload to box.

## Source verification
- ECC SHA-256: `0f75dd10ed77214c5cf159d40f909cd402231761886cb0ed3821368ac0ab1853` (matches brief + cad-font-study)
- Isolated copy: `candidates/[ECC_DWG]-source-copy.pdf` (hash verified at copy time)
- HVAC hash recorded for contrast only; HVAC mutations **not** re-run this batch
- Originals under `test_files/` remain untouched

## Case selection (primary variable = FONT / encoding family)

Source of identifiers: prior inventory table + `scripts/experiment_cad_font_edits.py` TEXT_CASES + `output/pdf/cad-font-study/results.json` (seq / before / after / font). **Not invented.**

| case_id | seq | signature (historical) | before → after | primary variable |
|---|---:|---|---|---|
| ecc-1 | 31 | mc_malformed_pairing | 專案名稱 → 專案圖名 | **DFKaiShu Type0 Identity-H** CJK ideograph swap (名稱→圖名) vs prior HVAC PMingLiU mc |
| ecc-2 | 38 | mc_malformed_pairing | 平面配置圖 → 機房配置圖 | **DFKaiShu** multi-ideograph swap (平面→機房) — second mc on same Kai face |
| ecc-3 | 57 | verification_failed | 113.05.03 → 113.05.05 | **DFKaiShu** same-length digit date vf vs prior HVAC JhengHei date (case7) |

**Deferred / not this batch**
- ecc-4 seq60 [ECC_DWG]→ECC-3: length-changing TJ; neighbors 圖號/頁碼 in same column — higher collision risk; keep for a later focused batch
- HVAC JhengHei: redundant with case7 (already non-PMingLiU pilot)
- HVAC DFKaiShu shows: no explicit CASES case_id — do not invent
- CHB / [AIRPORT_CODE]: vector — classify only
- 01_報告書 DFKaiShu: no documented case_id

## Per-case hypotheses (max 3) + falsification

### ecc-1 / seq=31 / mc_malformed_pairing
- H1: Engine prepare max_tier=1 rejects with `mc_malformed_pairing` on this DFKaiShu show → FALSIFY: live probe reason/detail
- H2: `encode_strict` + glyph_gate succeed for 專案圖名 on DFKaiShu ToUnicode/CID map → FALSIFY: CidCapabilityFailure or gate error
- H3: CID hex splice preserves F2 font_resource / Tm / neighbors; crop changes; outside halo 0; saveIncr reopen decodes → FALSIFY: structure/render/reopen checks

### ecc-2 / seq=38 / mc_malformed_pairing
- H1: Same mc reject on different Kai show (平面配置圖) → FALSIFY: prepare reason
- H2: Multi-glyph 平面→機房 encodes cleanly on same F2 face → FALSIFY: encode_strict
- H3: Splice+checks pass without scaling to old bbox → FALSIFY: structure/render/reopen

### ecc-3 / seq=57 / verification_failed
- H1: prepare fails `verification_failed` (expect fingerprint phrasing if exposed) → FALSIFY: probe reason/detail
- H2: Digit-only same-length edit on DFKaiShu needs ~0 TJ compensation → FALSIFY: |kern| measurement
- H3: Standalone splice still yields no-jump text despite engine reject → FALSIFY: structure/render/reopen

## Proposed edit methods (ordered)
- **M1**: `TieredCommitEngine.prepare` max_tier=1 — record reason (expect reject)
- **M2**: replay + CID `encode_strict` + stream splice on isolated candidate copy
- **M3**: TJ trailing compensation if advance delta — **never** scale glyphs to old bbox

## Evidence plan (each case)
- `structure_notes.json`, `live_engine_probe.json`, `object_diffs.json`, `neighbor_notes.json`
- `render-before.png` / `render-after.png`, `render_diff_notes.json`, `save_reopen_notes.json`
- `case_record.json`, failed methods, suggested product/regression notes
- Stop rule: after 3 attempts with no new evidence → blocked/insufficient_evidence

## Acceptance gate
`accepted_for_code` only if all 7 brief criteria hold **in this run**. Expect **none**: UI unverified; engine expected to reject. Experiment splice ≠ product acceptance.

## Constraints checklist
- [x] No product source edits
- [x] Isolated copies under this evidence folder only
- [x] No cloud upload of PDF binaries; box mirror JSON/MD only
- [x] No invented case_id/hashes
- [x] Vector = classify only
- [x] One primary variable family (DFKaiShu / CMap) per case vs HVAC priors
- [x] Max 3 cases this batch (within 2–4)
