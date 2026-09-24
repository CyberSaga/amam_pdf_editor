# HVAC Bb PDF：10 處 PyMuPDF 實際編輯紀錄

2026-09-21，PyMuPDF 1.27.1。來源為 `test_files/[HVAC_DWG_PDF]`，50 頁。本次完成 10 處文字修改並存檔重開；原始檔未變。修改內容是外觀實驗樣本，不代表設計圖說的正式工程修訂。

成果：`output/pdf/manual-font-study/[HVAC_PYMUPDF_PDF]`。同目錄的 `comparison-10.png` 是逐處對照，`01-before.png` 至 `10-after.png` 是 6 倍渲染裁切，`results.json` 保存每筆原文、替換文、字型資源、Tf/Tm/CTM/Tz、串流位址、原始與替換 bytes、補償量及驗證結果。

## 10 個已完成樣本

頁數從 1 起算；seq 是內容串流中的文字顯示操作識別，不是 PyMuPDF span index。

| 編號 | PDF 頁／seq | 修改前 → 修改後 | 保留字型 | TJ 尾端補償 |
|---|---|---|---|---:|
| 1 | 5／11 | 空調冰水管線系統圖(1) → 空調冰水管線系統圖(4) | PMingLiU | 0 |
| 2 | 5／16 | 空調冷卻水管線系統圖(1) → 空調冷卻水管線系統表(1) | PMingLiU | 0 |
| 3 | 5／6 | 空調系統封面 → 空調系統圖說 | PMingLiU | 0 |
| 4 | 5／7 | Chilled Water Distribution System Diagram(1) → …Diagram(4) | ArialMT | 0 |
| 5 | 5／18 | 1F Chilled Water System Plan Layout → 2F… | ArialMT | 0 |
| 6 | 5／26 | Drawing List → Drawing Title | ArialMT | +333 |
| 7 | 6／60 | 2026.05.15 → 2026.05.16 | MicrosoftJhengHeiRegular | 0 |
| 8 | 6／58 | 空調系統設計圖說A版 → 空調系統設計圖說B版 | MicrosoftJhengHeiRegular | −79 |
| 9 | 7／7 | Buffer Tank → Tank Buffer | ArialMT，普通矩陣 | 0 |
| 10 | 7／5 | Buffer Tank → Tank Buffer | ArialMT，鏡射矩陣 | 0 |

第 9、10 筆在原圖本來就是旋轉／鏡射呈現，本實驗保留該方向。對照總圖為方便並排，將這兩筆裁切額外旋轉；個別 PNG 保持 PDF 顯示方向。

## 重跑方式

在專案根目錄執行：

```powershell
.venv\Scripts\python.exe -u scripts/experiment_hvac_font_edits.py "test_files/[HVAC_DWG_PDF]"
```

腳本使用專案現有的 CID 編碼及 lexer，不依賴 PDF-XChange、Acrobat 或系統安裝字型。可加 `--output <另一個資料夾>`；會覆寫輸出資料夾內的實驗成果，不覆寫輸入。固定案例只適用這份原檔，不是通用 PDF editor。

成功條件先對原檔執行 `--verify-only <原檔>`，在 case 1 缺少替換文字時失敗。對成品的同一驗證通過。缺字負例 `空調冰水管路系統圖(1)` 也有實測：原字型沒有可證明的「路」CID，`encode_strict` 回報 `type0_unicode_unmapped`，不寫入猜測字碼。

## 實際有效的寫入方法

1. 用 `replay_page_streams` 找到指定 page、seq 的原始 `Tj`，核對原文字與原 bytes。不能對整份 PDF 做字串 replace，也不能只找第一個 `Buffer Tank`。
2. 用 `DocumentFontRegistry.capability(page, resource)` 取得該頁原資源；使用 `cid.encode_strict(new_text)` 與 `cid.glyph_gate(...)` 證明 CID 唯一、字形存在。Identity-H 的兩位元組碼是 CID，不能直接寫 `text.encode('utf-16-be')`。
3. 保留 `/Font` 資源與原來的 `Tf`、`Tm`、`cm`、`Tz`、`Tc`、`Tw`、`Ts`、`Tr` 及內容標記。等 advance 的文字只替換 `<hex>` operand；不 redaction、不另加文字覆蓋原字。
4. 長度／寬度改變時，本次原操作都是單一 hex `Tj`，改成 `[<new_CIDs> K] TJ`，其中 `K = (advance_new - advance_old) × 1000 / Tf`。advance 由原 `/W`、`/DW` 與 `Tc` 算出。正 K 拉回筆位置，負 K 向前補；原 Tz 和矩陣會自然作用到 TJ 位移。case 6 實際為 +333，case 8 為 −79。這是保留後續文字的起點，不是把新文字壓縮成舊字串寬度。
5. 用 `StreamReplacement` 與 `splice_stream` 核對 SHA-256 和預期 bytes，僅接合指定範圍。呼叫 `doc.update_stream(xref, patched_bytes, compress=True)` 寫入原內容串流。
6. 複製原檔後對副本 `saveIncr()`，關閉再 `fitz.open()` 驗證。增量存檔新增 1 個交叉參照串流是正常現象；不能把 xref 數量增加誤判為換字型。初次用完整 save 的試驗還觀察到 dictionary key 排序正規化，因此最終成果採增量方式，便於嚴格核對未改物件。

API 可參考官方 [`Document.update_stream`](https://pymupdf.readthedocs.io/en/latest/document.html#Document.update_stream) 與 [`Page.rotation_matrix`](https://pymupdf.readthedocs.io/en/latest/page.html#Page.rotation_matrix)。本次記錄以本機 1.27.1 實測為準。

## 字級不能只用一個數字重建

case 1 原始 `/C2_1 140.644 Tf`，`Tm=(0,-0.06,0.06,0,623.16,807.18)`，CTM 約為 identity，`Tz=79.9805`。垂直尺度為 `140.644 × 0.06 = 8.43864 pt`，水平方向另乘 `0.799805`。

同一段文字 `get_text('dict')` 的 size 約 **7.54683**，`get_texttrace()` 的 size 約 **6.74927**；它們都不能直接代替完整的原始文字變換。前者在此樣本接近 `8.43864 × sqrt(0.799805)`，後者接近 `8.43864 × 0.799805`。這是這個實際樣本的量測，不是對所有 PDF 抽取 API 的通則。僅憑 font 名稱加 size 重新 `insert_text`，缺少水平縮放、旋轉與鏡射資訊。

## 驗證證據與適用邊界

- 10 筆替換文字全部在存檔重開後讀回，10 個裁切全部有實際像素改變；每筆原字型名稱、trace size、方向、顏色、不透明度、render mode、起始 origin 與原文字狀態相同。
- 第 5、6、7 頁以 2 倍解析度比較，目標前後 bbox 聯集加 3 pt 邊界以外，變動像素各為 **0**。10 個 6 倍裁切完成目視比較，筆形與排版一致；正常方向和鏡射都保留。
- 僅修改內容串流 xref **28、39、52**。其餘 **10,676 個既有物件**保持相同：非 stream 比較物件表示、stream 比較解碼後 bytes；包括字型程式、ToUnicode、圖片及其他頁內容。原檔 SHA-256 在執行前後相同。
- 成品已透過開檔流程載入自家 PDF 編輯器，確認第 5 頁 250% 顯示，截圖為 `03-project-editor-pymupdf-result.png`；逐處高倍率判讀以 10 組裁切為準。
- `ruff check .` 通過；CID hex Tj、marked-content admission、TRM admission 三組既有測試 **157 passed**。未修改正式產品程式，未跑整個 Qt／全專案測試套件。
- 尚未驗證缺字補嵌入、跨 run、換行、任意多項 TJ、超出空白區、Form XObject、簽章等情況。不能把本腳本繞過產品 gate 的做法直接當作全面放寬 gate 的依據。

## 對目前程式的具體線索

同 10 筆在 `TieredCommitEngine(max_tier=1).prepare(...)` 探測結果全部拒絕：

| 樣本 | 拒絕碼 | 本次觀察 |
|---|---|---|
| 1–6 | `mc_malformed_pairing` | wrapper 被判定 unclosed 或跨 q/Q boundary |
| 7–9 | `verification_failed` | scratch apply 回報 page fingerprint changed |
| 10 | `trm_reflected` | 原文字的負 determinant 被拒絕 |

探測的 `expected_origin` 和 `target_bbox` 已轉到視覺座標，避免將 rawdict 的未旋轉座標誤傳。資料保留於 JSON。這些是可重現的拒絕結果，**不是已證明的完整 UI 消失根因**；特別是 scratch fingerprint 還需要獨立追查。

目前 `TextCommitSettings` 預設 `engine='tiered'`、`max_tier=0`、`strict=False`、`preview='legacy'`。因此僅啟用 tiered 名稱或提高 max_tier，無法保證這些案例走到保留原字型路徑。下一步應用本次 10 筆作回歸樣本，逐層查明拒絕與實際 fallback；保存 preview/commit 的相同資源與矩陣，而不是再猜系統字型名稱。此次沒有修改正式 engine 或 UI 行為。

## 早期操作與 TypeSafe 的角色

自家編輯器早期 UI 編輯曾出現文字消失，已復原，截圖 `01-project-editor-disappeared.png` 保留為失敗證據。後續 PDF-XChange 參考操作依使用者指示停止，該軟體的未儲存編輯與 `02-reference-case01-after.png` 不計入本次成功樣本；`[HVAC_MANUAL_PDF]` 也不是本次交付成品。

已閱讀 typesafe-ai skill 與 [System One 文件](https://docs.typesafe.ai/concepts/system-one)。Jev 的文字介面不適合作字形像素驗證；此次未呼叫 TypeSafe 模型、未將 PDF 上傳。外觀結論來自本地 PyMuPDF 渲染、物件核對與目視檢查。
