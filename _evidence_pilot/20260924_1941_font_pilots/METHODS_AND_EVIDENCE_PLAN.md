# Methods + evidence plan (BEFORE edits) — 20260924_1941 Asia/Taipei (UTC+8)

## Goal
Honest true-text pilots for **five non-default font candidates** from `_evidence_pilot/20260924_1908_font_search` `PARENT_SUMMARY.top_pilot_candidates`. No product source changes. Isolated copies only under `candidates/`. No PDF upload to box (JSON/MD mirror only).

## Source verification
- HVAC SHA-256: `9da93de982145c46af0d34a978b4bbaa1167f0937327dedb44ecad4d50fca0a2`
- ECC SHA-256: `0f75dd10ed77214c5cf159d40f909cd402231761886cb0ed3821368ac0ab1853`
- Isolated copies: `candidates/ECC-source-copy.pdf`, `candidates/HVAC-source-copy.pdf` (hash verified at copy time)
- Originals under `test_files/` remain untouched

## Case selection (labels — NOT invented integer case_ids)

Lineage: `candidate_discovered` from 20260924_1908 font search. All records set `has_explicit_case_id: false`.

| label | PDF | page | seq | font / resource / xref | before → after (planned) | primary variable |
|---|---|---:|---:|---|---|---|
| cand-ecc-jhenghei-seq0 | [ECC_DWG] | 0 | 0 | MicrosoftJhengHeiRegular / F1 / 13 | 排煙室 → 排煙區 | ecc_jhenghei_plan_label (vs HVAC case7 JhengHei date / ECC Kai) |
| cand-hvac-simsun-2f | HVAC Bb | 6 | 4 | SimSun / C2_0 / 9185 | 2F-平台 → 2F-平臺 (or encode fallback) | cjk_song_simsun_cad_labels |
| cand-hvac-kai-cover | HVAC Bb | 0 | 7 | DFKaiShu-SB-Estd-BF / F5 / 10663 | [CLIENT_ORG] → [CLIENT_ORG_SITE] | hvac_kai_cover_vs_ecc_titleblock |
| cand-hvac-trebuchet-m5 | HVAC Bb | 3 | 53 | TrebuchetMS / C2_4 / 9167 | M5 System… → M6 System… | latin_specialty_trebuchet_cid |
| cand-hvac-yahei-bold | HVAC Bb | 3 | 1 | MicrosoftYaHei-Bold / C2_1 / 9161 | 空調系統 → 通風系統 (or encode fallback) | cjk_yahei_bold_beyond_jhenghei |

Fingerprint source: `20260924_1908_font_search/FINGERPRINTS.json` + `NONDEFAULT_CANDIDATES.json`.

## Per-case hypotheses (max 3) + falsification

### cand-ecc-jhenghei-seq0
- H1: Engine prepare max_tier=1 rejects this ECC F1 JhengHei plan label → FALSIFY: live probe reason/detail
- H2: encode_strict+glyph_gate succeed for 排煙室→排煙區 on ECC MicrosoftJhengHeiRegular → FALSIFY: CidCapabilityFailure / gate
- H3: CID splice preserves F1/Tm/neighbors; crop changes; outside halo 0; saveIncr reopen → FALSIFY: structure/render/reopen

### cand-hvac-simsun-2f
- H1: prepare rejects SimSun CAD label (rotated/reflected Tm dir~(0,1)) → FALSIFY: probe reason
- H2: 2F-平台 same-length CJK/Latin mix encodes on SimSun Identity-H → FALSIFY: encode_strict
- H3: splice preserves C2_0 + negative/rotated det(Tm); neighbors + halo → FALSIFY: structure/render/reopen

### cand-hvac-kai-cover
- H1: prepare rejects HVAC cover Kai (family known on ECC; different layout) → FALSIFY: probe reason
- H2: [CLIENT_ORG]→[CLIENT_ORG_SITE] encodes on HVAC DFKaiShu F5 → FALSIFY: encode_strict
- H3: splice preserves F5/Tm/neighbors on cover block → FALSIFY: structure/render/reopen

### cand-hvac-trebuchet-m5
- H1: prepare rejects TrebuchetMS Identity-H Latin specialty CID → FALSIFY: probe reason
- H2: M5→M6 single-char Latin encodes; kern small → FALSIFY: encode_strict / |kern|
- H3: splice preserves C2_4 + rotated Tm; neighbors + halo → FALSIFY: structure/render/reopen

### cand-hvac-yahei-bold
- H1: prepare rejects sparse MicrosoftYaHei-Bold (large Tf, rotated) → FALSIFY: probe reason
- H2: 空調系統 same-length CJK swap encodes on YaHei-Bold → FALSIFY: encode_strict
- H3: splice preserves C2_1 + rotated Tm; neighbors + halo → FALSIFY: structure/render/reopen

## Proposed edit methods (ordered)
- **M1**: `TieredCommitEngine.prepare` max_tier=1 — record reason
- **M2**: replay + CID `encode_strict` + stream splice on isolated candidate copy
- **M3**: TJ trailing compensation if advance delta — **never** scale glyphs to old bbox

## Evidence plan (each case)
- `structure_notes.json`, `live_engine_probe.json`, `object_diffs.json`, `neighbor_notes.json`
- `render-before.png` / `render-after.png`, `render_diff_notes.json`, `save_reopen_notes.json`
- `case_record.json`, `failed_methods.json`, suggested product/regression notes, `unproven_limits.md`
- Stop rule: after 3 attempts with no new evidence → `blocked` / `insufficient_evidence`

## Acceptance gate
`accepted_for_code` only if all 7 brief criteria hold **in this run**. Expect **false**: UI unverified; engine expected to reject. Experiment splice ≠ product acceptance. Vector never counted as true-text success.

## Constraints checklist
- [x] No product source edits
- [x] Isolated copies under this evidence folder only
- [x] No cloud upload of PDF binaries; box mirror JSON/MD only
- [x] No invented integer case_id; labels + has_explicit_case_id:false
- [x] Vector = classify only (none in this five)
- [x] One primary variable (font family/face) per case vs prior PMingLiU/Arial/ECC-Kai pilots
- [x] Prefer short same-width-friendly replacements; TJ compensate if needed

## Chosen replacements after encode_strict probe (still BEFORE PDF mutation)
- cand-ecc-jhenghei-seq0: 排煙室 → **排煙房** (區 unmapped in subset; 房/口 OK)
- cand-hvac-simsun-2f: 2F-平台 → **1F-平台** (3/臺/地/走 unmapped; 1F reuses glyphs)
- cand-hvac-kai-cover: [CLIENT_ORG] → **[CLIENT_ORG_SITE]** (OK; note operator=TJ array single hex)
- cand-hvac-trebuchet-m5: M5… → **MM System Engineering Division** (digit 6 unmapped in Trebuchet subset)
- cand-hvac-yahei-bold: 空調系統 → **系統空調** (sparse face; only {空,調,系,統} mapped — reorder)
