# 本專案已有證據與限制

以下是 2026-09-21／22 的歷史紀錄，非每次任務的即時測試結果。先確認檔案存在、來源 hash 及目前 git 差異；找不到產物就標明缺失，不可重建一份摘要冒充原證據。

## 原始資料入口

- [HVAC 10 處實驗](../../../../docs/experiments/2026-09-21-hvac-font-edits.md)：每筆前後文、字型、Tj/TJ、矩陣、圖檔與驗證限制。
- [三份 CAD 實驗](../../../../docs/experiments/2026-09-21-three-cad-font-edits.md)：只有 ECC 的 4 筆是本輪真文字；CHB／[AIRPORT_CODE]向量結果不能補足真文字驗收。
- [真文字案例 manifest](../../../../test_scripts/fixtures/true_text_corpus/manifest.json) 與 [loader](../../../../test_scripts/true_text_corpus.py)：14 筆歷史案例（`class_id: historic`）的精確 source hash（`original_sha256`，`original` 為 null）、零起算頁碼、ShowOp 序號、替換文、字型的唯一案例清單；[acceptance 測試](../../../../test_scripts/test_text_commit_real_corpus_acceptance.py)只從 manifest 讀取。不要在 skill 複製另一份可漂移清單。
- [測試任務紀錄](../../../../plans/archive/2026-09-22-real-corpus-type0-acceptance-tests.md)：已建測試與原紅燈觀察，歸檔表示測試任務完成，不表示 engine 轉綠。
- [產品實作計畫](../../../../plans/2026-09-22-claude-code-true-text-implementation.md)：待執行提案；執行時先驗證具體假說。若日後歸檔，以 `rg --files plans` 找同名檔；不要自行啟動歷史 executor。

## 已證實到哪裡

| 證據 | 能支持 | 不能支持 |
| --- | --- | --- |
| HVAC 10 筆、ECC 4 筆保留原 CID/resource 的腳本修改與重開 | 這些固定來源／替換文有可行方法 | 正常 UI 已支援、任意新字皆可 |
| HVAC 2x 非目標差異 0；CAD MuPDF/Poppler 非目標差異 0 | 各報告所載 renderer 和遮罩下的結果 | 所有 14 筆目前都有雙 renderer 產品驗收 |
| 成果載入 app 的截圖 | 本程式能顯示腳本成果 | 使用者可透過編輯 UI 產生同樣結果 |
| 舊 engine 測試紅燈 | 曾觀察 8 筆 mc_malformed_pairing、5 筆 verification_failed、1 筆 trm_reflected | 已證明所有 UI 異常的因果根源或目前仍相同 |

舊測試為一個 14 筆 prepare aggregate 加兩個文件 roundtrip，共 3 個 pytest 失敗；不能把測試數 3 誤寫成只測 3 處。測試只用 MuPDF，沒有正常 UI 操作。要追查時在 repo 根目錄執行：

```powershell
.venv\Scripts\python.exe -m pytest -q test_scripts/test_text_commit_real_corpus_acceptance.py
```

## 可重用的實測線索

- HVAC 有 PMingLiU、ArialMT、MicrosoftJhengHeiRegular，ECC 有 DFKaiShu-SB-Estd-BF。保留原資源、CID、完整文字狀態是成功方法，換系統字型不是。
- HVAC 第一筆 `Tf=140.644`、`Tm=(0,-.06,.06,0,623.16,807.18)`、`Tz=79.9805`。同一筆 dict size 約 7.54683、trace size 約 6.74927；僅憑 size 重建會丟失尺度資訊。此數值關係是個案，不能泛化為 API 通則。
- HVAC `Drawing List→Drawing Title` 尾端 TJ 為 +333，A→B 為 −79；ECC `[ECC_DWG]→ECC-3` 為 −500。這些是獨立已知值，可防止測試只複製實作公式。
- ECC 曾試較長 `[ECC_DWG_LONG]`，字型檢查通過卻太靠近欄線。因此仍需檢查可用空間，不能只核對字型。
- `mc_malformed_pairing`、scratch fingerprint 與 reflected TRM 是已知診斷方向；原報告明確沒有證明完整 UI 根因。實作計畫的因果措辭不可取代重現與反例。
- PDF-XChange 參考操作已停止，未儲存內容與其截圖不計成功。

產物入口是 repo 的 `output/pdf/manual-font-study/` 與 `output/pdf/cad-font-study/`，含 PDF、results.json、前後裁切及 app 顯示截圖。這些是本地忽略檔，不保證每個 clone 都存在。原始 PDF 在 `test_files/`，驗證身分以測試中的 SHA-256 為準。
