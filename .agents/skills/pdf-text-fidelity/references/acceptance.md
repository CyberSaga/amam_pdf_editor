# 實際編輯驗收

## 選擇檢查範圍

根目錄相對路徑均以 repo 為準。依使用者授權的交付選擇檢查：實驗證明方法可行；engine 測試證明底層提交；正常 UI 操作才證明產品能做到。只交計畫時，把缺少的檢查寫入計畫，不自行執行引擎實作。

每筆記錄以下欄位，可直接放在該任務的計畫或結果 JSON，不強迫建立新系統：

| 欄位 | 意義 |
| --- | --- |
| case_id / source_sha256 | 穩定案例身分與來源版本 |
| page_index / show_seq / resource | 明示頁碼零起算；seq 是文字顯示操作序號，不是 span index |
| old_text / new_text / requested_style_changes | 指定結果；只有使用者要求的樣式差異才允許 |
| code_revision / dirty_diff_id / tool_versions | commit 加未提交差異識別（patch 檔或 hash）；不能只記 HEAD |
| phase / status / evidence_id | 各階段分別 pass、fail、not_run、blocked；空白不是通過 |
| observation / hypothesis / next_check | 分開事實、推測與下一個能區分原因的檢查 |
| artifacts / command / timestamp / limits | 相對路徑、重跑命令、時間與證據邊界 |

對當次要求的全部案例建立階段矩陣：選取與輸入、完成預覽、Apply、Undo、Redo、Save/Reopen。既有 HVAC／ECC 整合是 14 筆；新的真文字任務依該次約定的案例集合，不強迫擴成 14 筆。不要用一個 aggregate 綠燈隱藏個別未跑案例。修改版號或輸出 hash 改變後，只重用能證明仍適用的證據。

## 結構與視覺雙重檢查

- 寫入前確認原檔／原 slice，核對目標 run，特別是同頁同文但不同矩陣的 `Buffer Tank`。保留原檔，以新副本存結果。
- 使用原 font resource、嵌入字型與 ToUnicode/CID 證據；CID 必須嚴格編碼且 glyph gate 通過。Unicode 不等於 CID。
- 比較 `Tf`、`Tm`、CTM、`Tz`、`Tc`、`Tw`、`Ts`、`Tr`、色彩／透明度與原點。擷取 API 的單一 size 不足以重建字型外觀。
- 等 advance 可只 patch operand；已證實的單一 hex `Tj` 不等 advance 案例可改為 `[<CID> K] TJ`，`K=(new_advance-old_advance)*1000/Tf`。advance 使用原字型度量與 spacing；這個案例公式不能直接套到任意 TJ、垂直書寫或未知狀態。
- TJ 尾補償保存後續文字起點，並不壓縮新字。仍需檢查新字自然成長是否撞到鄰字或欄線。「接近」不自動等於碰撞；記錄新字 quad／bbox、鄰近幾何與實際間距，核對目前產品的 growth／overlap gate 及目視結果。有接觸、重疊、裁切或可讀性問題就不能算通過；若判定依賴未定義的留白要求，標明此不確定性，不自行發明距離閾值或縮字。
- 先檢查已解碼的替換文字確實存在，目標像素有改變；再檢查外觀保真。無修改、白字、刪光或拒絕提交不能靠「沒有非目標差異」通關。
- 相同 renderer/version、頁框、旋轉、DPI、色彩設定下各自比較 before/after。MuPDF 與 Poppler 各比自己的前後，不要求兩個 renderer 的像素彼此相同。
- 本批驗收為 6x 以上目標裁切、2x 以上整頁非目標像素差異 0；記錄前後 bbox 聯集與抗鋸齒邊界。遮罩須有依據，不能擴大到吞掉鄰字偏移。即使位於遮罩內，未改鄰字也須檢查位置與局部外觀。發現環境噪聲時先跑同檔重渲染對照，不能默默調高容差。
- 並排目視裁切確認字型、字重、水平／垂直尺度、基線、旋轉／鏡射；檢查正常閱讀倍率，避免只在巨幅放大圖看起來合理。保存渲染設定與圖檔，並實際開圖檢視。
- 重開後再核對文字、狀態及畫面。實驗的 `saveIncr()` 便於比較物件，並非產品唯一合法存法；完整存檔可能改 xref／序列化，應檢查語義與外觀，不能直接認定換字型。

## 正常 UI 操作的證據

有可用桌面工具時操作本專案程式；沒有桌面工具時，可用本地 PySide6 QTest 透過 widget 的滑鼠／鍵盤事件操作。可參考專案 `.claude/skills/verify/SKILL.md`（若存在），核心流程如下：

```python
import main
startup = main.run(argv=[pdf_path], start_event_loop=False)
app, view = startup["app"], startup["view"]
view.show()
# QTest 操作真實選取、文字輸入、Apply、Undo/Redo、Save/Open 控制項。
# 使用有截止時間的條件等待，等 preview/render 完成後 view.grab().save(...)。
```

QTest 直接呼叫 Model 或 Controller 修改方法屬 engine/controller 測試，不能標成 UI 操作。單純把腳本結果開進 app、點文件分頁或縮放，只證明可顯示。應從原檔在 UI 選取目標，輸入新文，取得完成的 preview，Apply 後核對實際 CommitOutcome，再 Undo/Redo、儲存、重開並檢查。

UI 與渲染工具不足時，不虛構截圖或宣稱通過；先完成能執行的底層檢查，列出 blocked 的特定階段與恢復方式。不要把工具失效改寫成產品失敗，也不要用第三方 PDF 編輯器成果代替本產品編輯。

## 負例與修正節奏

改到哪個 gate，就保留其反例：缺字／模糊 CID、真正 stale 的來源、malformed 或 hidden content、未證實的變換、空間衝突、過期 preview。不靠廣泛放行讓 14 筆通過；失敗不得偷偷進 legacy，應保持文件未變、保留輸入並回報拒絕。

先重現一筆，再用差分追查「腳本成功而產品失敗」的位置。根因需能解釋原失敗、讓同一案例轉綠，且相應反例仍拒絕。無新證據就不要重跑同一失敗命令或擴大改動。全部需求完成前不要把單一案例成功標成整體完成。

## 報告

寫清楚通過幾筆／要求幾筆、測了哪些階段、未測原因、成果與前後證據位置。fixture 缺失可依測試本身規則 skip，但完成統計須列 not_run，不能列 pass。執行專案適用 gates；文件／skill-only 修改以文件驗證與行為演練檢查，不用引擎測試數量冒充成果。
