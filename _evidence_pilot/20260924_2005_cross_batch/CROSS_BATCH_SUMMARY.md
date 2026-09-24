# 跨批次 Evidence 總表

時區戳記：20260924_2005 Asia/Taipei (UTC+8)

## 總覽

| 指標 | 數值 |
|---|---|
| 實驗路徑 `save_reopen_pass`（列計） | 14 |
| 產品 UI `ui_pass` | 0 |
| `accepted_for_code` | 0 |
| 產品原始碼修改 | 0 |

## 批次一覽

| 戳記 | 主題 | 本機路徑 |
|---|---|---|
| `20260924_1431` | failure-signature pilot (mc / vf / trm) | `_evidence_pilot\20260924_1431` |
| `20260924_1453` | same-signature expand + trm deepen | `_evidence_pilot\20260924_1453` |
| `20260924_1612` | 標楷體 DFKaiShu ECC pilots | `_evidence_pilot\20260924_1612` |
| `20260924_1908_font_search` | search-only non-default font inventory | `_evidence_pilot\20260924_1908_font_search` |
| `20260924_1941_font_pilots` | five non-default font isolation pilots | `_evidence_pilot\20260924_1941_font_pilots` |
| `20260924_1959_ui_flow` | product UI preview/Apply/Undo/Redo | `_evidence_pilot\20260924_1959_ui_flow` |

## 案例總表（實驗路徑）

| 批次 | ID／標籤 | 來源 | 字體 | 頁/seq | 原文→替換 | 產品／prepare 原因 | 實驗狀態 | 備註 |
|---|---|---|---|---|---|---|---|---|
| 1431 | `1` | HVAC | PMingLiU | 4/11 | 空調冰水管線系統圖(1)→空調冰水管線系統圖(4) | `mc_malformed_pairing` | save_reopen_pass | digit-only Type0 CID |
| 1431 | `7` | HVAC | MicrosoftJhengHeiRegular | 5/60 | 2026.05.15→2026.05.16 | `verification_failed` | save_reopen_pass | date digit; kern≈0 |
| 1431 | `10` | HVAC | ArialMT | 6/5 | Buffer Tank→Tank Buffer | `trm_reflected` | save_reopen_pass | det_tm=-0.0036 |
| 1453 | `2` | HVAC | PMingLiU | 4/16 | 空調冷卻水管線系統圖(1)→空調冷卻水管線系統表(1) | `mc_malformed_pairing` | save_reopen_pass | 圖→表 vs case1 digit |
| 1453 | `8` | HVAC | MicrosoftJhengHeiRegular | 5/58 | 空調系統設計圖說A版→空調系統設計圖說B版 | `verification_failed` | save_reopen_pass | nonzero TJ kern≈-79; check cases.json for exact strings |
| 1453 | `10-deepen` | HVAC | ArialMT | 6/5 | Buffer Tank→Tank Buf | `trm_reflected` | save_reopen_pass | shorter; det preserved; not new case_id |
| 1453 | `trm-sibling` | HVAC | — | — | —→— | `—` | blocked | no second trm_reflected case_id |
| 1612 | `ecc-1` | ECC | DFKaiShu-SB-Estd-BF | 0/31 | 專案名稱→專案圖名 | `mc_malformed_pairing` | save_reopen_pass | 標楷 F2/72 |
| 1612 | `ecc-2` | ECC | DFKaiShu-SB-Estd-BF | 0/38 | 平面配置圖→機房配置圖 | `mc_malformed_pairing` | save_reopen_pass | multi-ideograph |
| 1612 | `ecc-3` | ECC | DFKaiShu-SB-Estd-BF | 0/57 | 113.05.03→113.05.05 | `verification_failed` | save_reopen_pass | Kai digit date |
| 1612 | `ecc-4` | ECC | DFKaiShu-SB-Estd-BF | 0/60 | [ECC_DWG]→ECC-3 | `—` | deferred | column neighbor risk |
| 1941 | `cand-ecc-jhenghei-seq0` | ECC | MicrosoftJhengHeiRegular | 0/0 | 排煙室→排煙房 | `mc_malformed_pairing` | save_reopen_pass | F1/13 candidate_discovered |
| 1941 | `cand-hvac-simsun-2f` | HVAC | SimSun | 6/4 | 2F-平台→1F-平台 | `verification_failed` | save_reopen_pass | first SimSun; rotated Tm |
| 1941 | `cand-hvac-kai-cover` | HVAC | DFKaiShu-SB-Estd-BF | 0/7 | [CLIENT_ORG]→[CLIENT_ORG_SITE] | `mc_wrapper_not_pure_layer` | save_reopen_pass | new signature; TJ array |
| 1941 | `cand-hvac-trebuchet-m5` | HVAC | TrebuchetMS | 3/53 | M5 System Engineering Division→MM System Engineering Division | `verification_failed` | save_reopen_pass | TJ kern≈185 |
| 1941 | `cand-hvac-yahei-bold` | HVAC | MicrosoftYaHei-Bold | 3/1 | 空調系統→系統空調 | `verification_failed` | save_reopen_pass | sparse large Tf |

## UI 流程（1959，offscreen harness）

| case | preview | Apply | Undo/Redo | 總評 |
|---|---|---|---|---|
| 1 | blocked (`mc_malformed_pairing`) | blocked | skipped | ui_blocked |
| 7 | **pass** | blocked (`verification_failed`) | skipped | ui_blocked |
| 10 | blocked (`no_source_match`) | blocked | skipped | ui_blocked |
| ecc-1 | blocked (`mc_malformed_pairing`) | blocked | skipped | ui_blocked |

## 觀測到的 gate／簽章
- `mc_malformed_pairing`
- `verification_failed`
- `trm_reflected`
- `mc_wrapper_not_pure_layer`
- `no_source_match (UI span split on case 10)`

## 真文字成功範圍外（向量）
- [VECTOR_CHB_PDF]
- [VECTOR_AIRPORT_PDF]

## 到 `ui_pass` / `accepted_for_code` 的阻擋
- Engine prepare still rejects true-text path under max_tier=1 strict
- Case7 preview/commit fingerprint gap
- Case10 UI Buffer|Tank span split vs show-level target
- Undo/Redo unreachable until Apply commits

## 字體覆蓋進度

| 字體 | 已有實驗證據？ | 來源 |
|---|---|---|
| PMingLiU | 是 | HVAC 1/2 |
| MicrosoftJhengHeiRegular | 是 | HVAC 7/8；ECC cand seq0 |
| ArialMT | 是 | HVAC 10 |
| DFKaiShu（標楷） | 是 | ECC 1–3；HVAC cover cand |
| SimSun | 是 | HVAC cand |
| TrebuchetMS | 是 | HVAC cand |
| MicrosoftYaHei-Bold | 是 | HVAC cand |
| CHB／[AIRPORT_CODE] | 否（向量） | out of scope |

此總表為彙整，不構成 Claude Code 轉交；`accepted_for_code` 仍為 0。