# 三份 CAD PDF：12 處原字形保留編輯實驗

本次依使用者要求暫停正式引擎整合計畫，先擴充實際 PDF 編輯證據。
修改使用 PyMuPDF 1.27.1 與專案現有 lossless lexer / CID primitives，
沒有修改正式 model、controller 或 view，也沒有使用 PDF-XChange 編輯。

## 先辨識內容種類

| 原檔（均位於 test_files） | 真正的內容 | 本次測試 |
|---|---|---|
| [VECTOR_CHB_PDF] | 無字型、文字 trace、圖片或 Form XObject；12,920 個 MuPDF drawing records | 4 處細線向量數字 |
| [ECC_DWG].pdf | 有 MicrosoftJhengHeiRegular、DFKaiShu-SB-Estd-BF 兩個 Type0 字型 | 4 處原嵌入標楷體，與上次 HVAC 的三種字型不同 |
| [VECTOR_AIRPORT_PDF] | 無字型、文字 trace、圖片或 Form XObject；19,466 個 drawing records | 3 處襯線數字、1 處窄線向量英文字 |

因此不能把這次說成「三種新命名字型都通過文字引擎」。實際新增證據是：
**一種新的嵌入字型，以及兩份已轉曲 CAD 圖面的向量字形編輯。**
後兩者不能從 PDF 查出原始字型家族，也沒有 Unicode 可直接改。

## 實際修改

| 編號 | 檔案 / 位置 | 原內容 | 修改後 |
|---|---|---|---|
| 1–4 | CHB 頂部四個水平尺寸，由左至右 | 1000 / 1000 / 1000 / 1000 | 1001 / 1010 / 1100 / 1001 |
| 5 | ECC 右側專案欄標題 | 專案名稱 | 專案圖名 |
| 6 | ECC 右側圖名 | 平面配置圖 | 機房配置圖 |
| 7 | ECC 日期 | 113.05.03 | 113.05.05 |
| 8 | ECC 圖號 | [ECC_DWG] | ECC-3 |
| 9 | [AIRPORT_CODE]右側日期 | 110.04.29 | 110.04.24 |
| 10 | [AIRPORT_CODE]右下分類圖號 | MB-02 | MB-20 |
| 11 | [AIRPORT_CODE]左下管徑註記 | 150A*2 | 150A*1 |
| 12 | [AIRPORT_CODE]中段上方管線文字 | CHR 100A | CHS 100A |

這些是編輯方法的展示副本，不是設計內容變更指示。

## 方法 A：真正的 Type0 文字

ECC 四筆均沿用 `/F2`、xref 72 的 `DFKaiShu-SB-Estd-BF`。
原始狀態為 `Tf=246.092`、`CTM=[.06,0,0,.06,0,0]`、`Tz=75`，
且 `Tc=Tw=0`。原始垂直縮放量為 14.76552 pt，水平方向另外縮成 75%。
不能把擷取出的單一 size 當成完整字型樣式重新插入。

1. `replay_page_streams()` 定位實際 ShowOp，保留字型資源及全部文字狀態。
2. `DocumentFontRegistry.capability()` 取得原字型的 CID 對應。
3. `encode_strict()` 與 `glyph_gate()` 證明替代字元在該字型中確實可用；
   不把 Unicode 數值直接當 CID，也不靠系統字型補字。
4. 相同 advance 只替換 hex operand。前三筆的補償值都是 0。
5. 長度改變時，保留新文字的自然字寬，用尾端 TJ 補償恢復後續文字位置：

   `K = (new_advance - old_advance) * 1000 / Tf`

   第 8 筆 `[ECC_DWG] → ECC-3` 實際寫入：

   ```pdf
   [<004600440044002E0034> -500.0000000000] TJ
   ```

   這個 K 不會壓扁新文字；它只調整此次 show 完成後的文字游標。
6. `StreamReplacement` 帶原切片與 stream SHA-256，經 `splice_stream()`
   驗證後，使用 `Document.update_stream(..., compress=True)`。

存檔後重新開啟，逐筆比對文字、原字型、Tf、Tm、CTM、Tz、字距、基線原點、
顏色、透明度及 render mode。所有字型檔、ToUnicode 與其他非目標物件未改。

## 方法 B：向量字形，不能走 insert_text

先人工看渲染圖確認字義與來源，再以幾何區域定位完整筆畫；
本次沒有宣稱完成自動 OCR 或任意輸入文字。

1. 以 `Page.get_drawings()` 檢查目標及 donor 字形。donor 取自同一串字、
   相同尺寸與筆畫風格。例如日期的 9 改為該日期已有的 4；
   CHR 的 R 改用正下方 CHS 的 S。
2. 串接 `/Contents` 的**解碼內容**再解析，同步追蹤 `q/Q`、`cm`、`j`。
   兩份檔案真的會在串流邊界切開路徑，不能每個 stream 重設狀態。
   腳本只允許本次觀察到的平移 CTM 與有限 path grammar；未知操作直接拒絕。
3. 保留被移除路徑周圍的狀態操作，以 `n` 清除原目標路徑；
   插入原 donor 的 `m/l/c/re/h` 及 paint operator 原始位元組。
   每條 donor 路徑包在獨立 `q … Q`，設定其原 `j`，僅作平移。
   donor 本身留在原位，沒有以白色方塊覆蓋，也沒有點陣化文字。
4. 頁面上選定的位移須經
   `~(page.transformation_matrix * page.rotation_matrix)` 轉回 PDF 座標。
   [AIRPORT_CODE]頁面 `/Rotate=90`，不能直接把螢幕 x/y 寫成 PDF x/y。
5. 以 Decimal 累加這些 PDF 中大量相對平移；只對選定、完整落在單一
   stream 的路徑做 byte splice。被選路徑若跨 stream，當前腳本拒絕處理。
6. 重新開啟後，由 MuPDF 獨立解讀結果。檢查 donor 與新字形的每條線、
   Bezier 控制點、paint mode、填色、線色、線寬、端點、接合與透明度。
   原始 path bytes 必須精確複用；MuPDF float32 解讀座標的比較容差為
   0.002 pt，paint style 則完全相等。頁面像素比較沒有容差。

## 本次實際抓出的問題

- **筆畫各自有 lineJoin。** [AIRPORT_CODE] S 的部分筆畫是 `j=2`，部分是 `j=1`。
  最初只複製 path bytes 會沿用目標的接合方式；獨立樣式驗證失敗。
  修正為解析 `q/Q` 內的 j 狀態，並逐筆畫放回原 j，才通過。
- **浮點數先四捨五入再字串比較會誤判。** 字形移動後 MuPDF 解讀控制點
  最大差約 0.00019 pt，恰好跨過小數點二位的捨入邊界。
  改成直接比較幾何數值；原 stream slice 與複用 path bytes 仍是精確檢查。
- **字型一致不代表能放得下。** 曾試 [ECC_DWG_LONG]，字型驗證通過，但放大圖顯示
  最後一字過於接近右邊欄線，因此最終改測 ECC-3。正式功能仍需要成長空間判斷。

## 驗證與產物

先完成 verifier，再以三份未修改原檔執行 `--verify-originals`，三份均因
預期內容或幾何不存在而失敗（exit 1）。其後才實作 writer。

| 檔案 | MuPDF 216 dpi 目標像素變動 | Poppler 216 dpi 目標像素變動 | 兩者非目標像素變動 | 改動的 content xref |
|---|---:|---:|---:|---|
| CHB | 1,080 | 1,072 | 0 / 0 | 18 |
| ECC | 3,322 | 3,332 | 0 / 0 | 73、99 |
| [AIRPORT_CODE] | 1,671 | 1,626 | 0 / 0 | 13、18、20 |

12 個 8 倍局部渲染均有實際變動，已逐張目視檢查。向量案例的像素遮罩只涵蓋
被替換字形與抗鋸齒邊界，不把整段文字或整張圖排除。非目標內容串流、字型、
圖片及其他既存物件均保持一致；三份來源檔 SHA-256 均未變。
輸出使用 `copyfile()` 後 `saveIncr()`，此處只是實驗存檔策略，不是產品存檔方案。

成果位於 `output/pdf/cad-font-study/`：

- `chb-edited.pdf`、`ecc-edited.pdf`、`taoyuan-edited.pdf`
- 三張 `*-comparison.png`：每張四組左右對照，8 倍原始 PDF 渲染。
- `*-poppler-before.png`、`*-poppler-after.png`：第二套渲染器的整頁證據。
- `results.json`：來源與輸出 hash、實際修改、CID 狀態、donor 範圍與位移、
  原路徑 hash、物件及像素驗證數據。

重跑與驗證：

```powershell
.venv\Scripts\python.exe -u scripts/experiment_cad_font_edits.py
.venv\Scripts\python.exe -u scripts/experiment_cad_font_edits.py --verify-only
.venv\Scripts\python.exe -u scripts/experiment_cad_font_edits.py --verify-originals
```

最後一個命令預期 exit 1。腳本以原始檔 hash 防止把這批座標套到不同版本；
`--only chb|ecc|taoyuan` 可單獨實驗，但會只輸出該檔的 results.json。

已執行 `ruff check .`、lexer/CID 相關回歸測試（105 passed）。沒有改正式功能，
未執行整個產品測試套件或宣稱完成正式編輯流程驗收。

另外依專案 verify 技能，透過 `main.run(argv=[三份成果], start_event_loop=False)`
啟動真正的 PySide6 應用程式，以 QTest 點擊三個文件分頁及輸入縮放 70%，
等待每頁的 render quality 到 high，再以 `view.grab()` 留存畫面。
三份均成功載入並顯示；畫面副本為 `app-chb.png`、`app-ecc.png`、
`app-taoyuan.png`。這證明成果可由正式應用程式顯示，不代表其文字編輯 UI 已支援
本次方法。原有視窗的桌面工具啟用失敗，並已依工具規則停止重試。

## TypeSafe 使用範圍

已閱讀使用者指定的 typesafe-ai 技能與即時
[State](https://docs.typesafe.ai/concepts/state.md)、
[Models](https://docs.typesafe.ai/models.md) 文件。Jev 只接受文字，無法直接觀看
本次 PDF 字形；本機沒有 TYPESAFE_API_KEY，**本次沒有呼叫 Jev，也沒有上傳圖面**。
採用技能的分工原則：字義及樣本選擇由人工檢視，已知規則、CID、幾何和像素由
程式精確驗證。不能把 typed judgment 或機率當成字型保真證明。

## 對後續程式的實際結論

先將頁面分成真文字與向量字形兩條路徑。真文字延伸原 CID/resource 編輯證據；
轉曲頁則另需字形分組、字義標註與同風格 donor 庫。找不到可靠 donor 時，
目前方法不能承諾任意新字都保持外觀。本次沒有做缺字補齊、新字型嵌入、
任意變換、Form XObject 編輯或自動向量 OCR。
