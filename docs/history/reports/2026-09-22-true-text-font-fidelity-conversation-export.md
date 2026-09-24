# 真文字字型穩定編輯：對話紀錄與交接資訊

匯出日期：2026-09-22  
目的：保存本次 PDF 真文字字型穩定問題的需求演變、已取得證據、測試輸出與尚未實作的正式修改計畫，供後續 Claude Code 或工程師直接參考。

本檔是可交接的摘要型對話紀錄；不含系統指令、登入資訊或工具內部輸出。

## 對話決策紀錄

1. 使用者最初要求在 HVAC 圖說中手動驗證多處文字修改後，找出字型不跳動的可程式化做法。
2. 使用者明確否決把 PDF-XChange Editor 當成正式解法，要求以 PyMuPDF 與專案既有程式碼可實作的 API／參數為準。
3. 完成 HVAC 與三份 CAD PDF 的實驗後，使用者要求將向量／轉曲文字延後，只把真文字做到穩定。
4. 使用者要求工作拆為兩段：gpt-5.6-sol 建立驗收測試；Claude Code 依測試修改正式程式碼。
5. 使用者後續澄清當時只要計畫，不要直接實作；因此正式 production code 目前仍未依本計畫修改。

## 範圍與排除項目

本輪唯一的成功範圍是嵌入式 Type0 PDF 文字：

| PDF | 類型 | 筆數 | SHA-256 |
| --- | --- | ---: | --- |
| `[HVAC_DWG_PDF]` | Type0 真文字 | 10 | `9da93de982145c46af0d34a978b4bbaa1167f0937327dedb44ecad4d50fca0a2` |
| `[ECC_DWG].pdf` | Type0 真文字，`/F2`、`DFKaiShu-SB-Estd-BF` | 4 | `0f75dd10ed77214c5cf159d40f909cd402231761886cb0ed3821368ac0ab1853` |

`[VECTOR_CHB_PDF]` 與 `[VECTOR_AIRPORT_PDF]` 沒有可供此引擎重用的 font/text stream，屬向量／轉曲字形。它們已在 `TODOS.md` 延後處理，不能被計為真文字引擎成功，也不能成為自動 fallback。

## 已驗證的 14 筆案例

| PDF | page index | show sequence | 原文 | 替換文字 | 原資源 |
| --- | ---: | ---: | --- | --- | --- |
| HVAC | 4 | 11 | 空調冰水管線系統圖(1) | 空調冰水管線系統圖(4) | `C2_1` / PMingLiU |
| HVAC | 4 | 16 | 空調冷卻水管線系統圖(1) | 空調冷卻水管線系統表(1) | `C2_1` / PMingLiU |
| HVAC | 4 | 6 | 空調系統封面 | 空調系統圖說 | `C2_1` / PMingLiU |
| HVAC | 4 | 7 | Chilled Water Distribution System Diagram(1) | Chilled Water Distribution System Diagram(4) | `C2_0` / ArialMT |
| HVAC | 4 | 18 | 1F Chilled Water System Plan Layout | 2F Chilled Water System Plan Layout | `C2_0` / ArialMT |
| HVAC | 4 | 26 | Drawing List | Drawing Title | `C2_0` / ArialMT |
| HVAC | 5 | 60 | 2026.05.15 | 2026.05.16 | `C2_1` / MicrosoftJhengHeiRegular |
| HVAC | 5 | 58 | 空調系統設計圖說A版 | 空調系統設計圖說B版 | `C2_1` / MicrosoftJhengHeiRegular |
| HVAC | 6 | 7 | Buffer Tank | Tank Buffer | `C2_1` / ArialMT |
| HVAC | 6 | 5 | Buffer Tank | Tank Buffer | `C2_1` / ArialMT，鏡射 |
| ECC | 0 | 31 | 專案名稱 | 專案圖名 | `F2` / DFKaiShu-SB-Estd-BF |
| ECC | 0 | 38 | 平面配置圖 | 機房配置圖 | `F2` / DFKaiShu-SB-Estd-BF |
| ECC | 0 | 57 | 113.05.03 | 113.05.05 | `F2` / DFKaiShu-SB-Estd-BF |
| ECC | 0 | 60 | [ECC_DWG] | ECC-3 | `F2` / DFKaiShu-SB-Estd-BF |

三個已獨立量測、不能由引擎回報值反推的變寬 `TJ` 尾端補償為：HVAC `Drawing List → Drawing Title` 的 `333`、HVAC `A版 → B版` 的 `-79`，以及 ECC `[ECC_DWG] → ECC-3` 的 `-500`。

## 已建立的驗收測試與結果

測試檔：`test_scripts/test_text_commit_real_corpus_acceptance.py`。它固定 fixture hash 與上述十四筆案例，並驗證：

- 原 Type0 font resource、CID mapping 與嵌入字型維持不變。
- `Tf`、`Tm`、CTM、`Tz`、`Tc`、`Tw`、rise、render mode 與文字原點維持不變。
- 變寬案例的 `TJ` 補償、僅目標 stream 修改、`saveIncr` 後重開與文字解碼。
- 目標區域外的 MuPDF 像素差異為零。
- fixture 在本機存在時不得 skip；CI 缺少 fixture 才能 skip。

實際執行：

```powershell
.venv\Scripts\python.exe -m pytest -q test_scripts\test_text_commit_real_corpus_acceptance.py
```

輸出：`3 failed in 107.65s`，這是實作前應保留的紅燈基線。十四筆 prepare 拒絕的完整分布：

- 8 筆 `mc_malformed_pairing`：HVAC `page_index=4` 的六筆，以及 ECC `show_seq=31`、`38`。
- 5 筆 `verification_failed: candidate failed to apply on scratch: page fingerprint changed since the plan was prepared`：HVAC `page_index=5/show_seq=60,58`、`page_index=6/show_seq=7`；ECC `show_seq=57,60`。
- 1 筆 `trm_reflected`：HVAC `page_index=6/show_seq=5`。

靜態檢查結果：

```text
.venv\Scripts\python.exe -m ruff check test_scripts\test_text_commit_real_corpus_acceptance.py
All checks passed

.venv\Scripts\python.exe -m ruff check .
All checks passed
```

`py_compile` 亦通過。測試目前是 model/engine 驗收門檻；正式實作另須增加經 `PDFModel` 與 Qt UI 的 run-level edit、save/reopen 與 hit-test 驗收。

## 已確認的正式程式缺口

下列結論來自真實 corpus 的紅燈與原始碼檢查，不可用向量實驗替代：

1. `model/text_commit/inspect.py` 的 `_canonical_object_digest()` 與 `_fold_canonical_value()` 讓 scratch serialization 的 `1.0` 與 `1` 產生不同 fingerprint；應改為精確語意 canonicalization，不能加入數值容差，也不能削弱 stale 保護。
2. `model/text_commit/replay.py` 記錄 `crossed_q`，`model/text_commit/marked_content.py` 將它直接歸類為 malformed。有效的 BDC/EMC 範圍跨越 `q/Q` 不應因此被一概拒絕；真正的配對、可見性、OCG、範圍與 malformed 防護必須保留。
3. `model/text_commit/transforms.py` 的 `shape_reject_reason()` 拒絕所有 reflected TRM。只應允許實測的鏡射 Type0 條件：有限、非奇異、正交、等比例、cardinal baseline、fill mode，並同時通過 CID、glyph coverage 與 advance 證明。
4. 正常使用者流程應預設 Tier 0/1 與 plan preview，而不是把 legacy 或 CSS preview 當成靜默 fallback。來源 font resource、`Tf`、`Tm`、CTM、spacing、rise 均不可被重建流程改寫。
5. 普通 Apply 必須以同一份 current preview token/snapshot/patch commit；拒絕、preview failure、token stale 或未同意降級時保留使用者輸入。只有獨立「重建文字」操作可選擇 legacy，且需將 `allow_rebuild` 明確設為 `True`。

## Claude Code 的實作契約

開始前必讀：

- `CLAUDE.md` 與 `AGENTS.md`
- `plans/2026-09-22-claude-code-true-text-implementation.md`
- `plans/archive/2026-09-22-real-corpus-type0-acceptance-tests.md`
- `test_scripts/test_text_commit_real_corpus_acceptance.py`

必須做：

- 先跑上述 red-first 測試，保留紅燈證據，再依正式計畫修正。
- 以 `DocumentFontRegistry`、strict CID encoding、`StreamReplacement`／`splice_stream` 重用來源字型資源。
- 等寬時只替換 hex operand；變寬時使用 `[<new-cids> K] TJ`，其中 `K = (new_advance - old_advance) * 1000 / Tf`。
- 將 shipped defaults 改為 `engine="tiered"`、`max_tier=1`、`preview="plan"`。
- 新增 `EditTextRequest.allow_rebuild: bool = False`，普通 Apply 永不自動呼叫 legacy。
- 為 numeric stale、q/Q marked-content、鏡射 admission、缺字、stale preview token、明確重建同意與拒絕後零 mutation 補正反向測試；再補 QTest UI 流程。

禁止做：

- 不得修改 fixture hash、案例、assertion、視覺／資源門檻或 skip 邏輯來讓測試通過。
- 不得插入系統字型、嵌入新字型、rasterize、用 CSS preview 冒充高保真、推測向量字形或自動 legacy redact/reinsert。
- 不得處理 vector/outlined letters、multi-run/paragraph replacement、Form XObject、任意 shear/rotation，或改寫使用者的實驗 script。
- 不得 commit 或 push，除非使用者另行要求。

完成條件：十四筆均經正常 UI 的 run-level edit 成為高保真提交；無 `DEGRADED_COMMITTED`、系統字型或 legacy branch；通過 focused pytest、相關測試、完整 pytest、`mypy model/ utils/`、`ruff check .`，並以 MuPDF 及 Poppler 驗證目標外像素零差異。

## 目前狀態與相關產物

- 向量文字延期決策在 `TODOS.md`。
- HVAC 實驗：`docs/experiments/2026-09-21-hvac-font-edits.md`、`scripts/experiment_hvac_font_edits.py`。
- CAD 實驗：`docs/experiments/2026-09-21-three-cad-font-edits.md`、`scripts/experiment_cad_font_edits.py`。
- Claude Code 實作計畫：`plans/2026-09-22-claude-code-true-text-implementation.md`。
- gpt-5.6-sol 測試計畫：`plans/archive/2026-09-22-real-corpus-type0-acceptance-tests.md`。

本次已嘗試建立 Claude Code 背景執行工作，但本機 Claude Code 回報登入逾期並要求 `/login`，因此它沒有修改 production code。後續登入後，應使用本檔內容連同上述四份必讀檔案重新交接。
