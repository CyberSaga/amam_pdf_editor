# 設計審查｜OCR 文字層獨立於 Undo／Redo

## Result

**建議保留可立即搜尋、可直接存進 PDF 的 OCR 文字層，並由 `DocumentSession` 持有每個邏輯頁目前接受的版本。** Undo／Redo 只移動一般編輯命令。只要原頁仍存在、座標仍可證明有效，每次成功移動歷史後，該頁都應有且只有一份目前接受的 OCR。Undo／Redo 本身不能選回舊 OCR、清除新 OCR、增加 OCR 版本，或消耗一個 OCR 歷史步驟。

原草案的「先驗 vector digest，再補 OCR，在同一 write lease 內完成」應保留。需要修正三點：

1. **整份文件、單頁物件圖、文字 patch 有三條不同的還原路徑。** 只掛 `_restore_doc_from_snapshot()` 會漏掉後兩條。
2. **高保真文字 undo 可能在「補回 OCR」之前就失敗。** 同頁加 OCR 會改變整頁指紋，即使原文字 stream 一個 byte 都沒變。
3. **看到 marker 不能直接跳過，找不到 marker 也不能直接重寫。** 必須區分目前版本、舊版本、已清除、未受管理的隱形文字，以及已損壞而無法辨認的受管理層。

先前 B7 提案每頁記一筆 `ocr_page`，會改變 Ctrl+Z 的下一步，也會在 OCR 抵達時清空既有 redo。依本卡業主決定刪除這部分。保留 H22 的裁決：向量驗證期間排隊的是 OCR **套用**，辨識可繼續。`equivalent()` 的正規化仍是暫定決策，本卡不需要擴大它。[B7 舊提案](C:/Users/wilson/Documents/amam_pdf_editor/plans/b7-design-astra.md:50) · [業主最後裁決](C:/Users/wilson/Documents/amam_pdf_editor/plans/owner-decisions-1124.md:54) · [record 清除 redo](C:/Users/wilson/Documents/amam_pdf_editor/model/edit_commands.py:1455)

### 1. 歷史與還原入口

| 路徑 | 本分支實作及設計掛點 |
|---|---|
| 文件層 Ctrl+Z／Redo | `PDFController.undo()`／`redo()` 各呼叫一次當前 session 的 `CommandManager`。Manager 先看 stack 頂端，呼叫 `cmd.undo()`／`cmd.execute()`，成功才移動命令；`finally` 會推進 revision。這是文件歷史的共用交易入口。輸入框中尚未提交的 Ctrl+Z／Redo 另走 Qt widget，不應觸發 OCR。見 `controller/pdf_controller.py:5214`、`:5238`，`model/edit_commands.py:1481`、`:1514`，`view/text_editing.py:404`、`:413`。 |
| `SnapshotCommand` | Redo 還原 `_after_bytes`，undo 還原 `_before_bytes`。`_restore_doc_from_snapshot()` 開啟、重新驗證新 handle，關閉舊 handle，恢復 xref epoch、maintenance book 與 tool page state；command 再刷新索引。任一頁的命令均可能覆寫**其他頁**較晚加入的 OCR。見 `model/edit_commands.py:1319`、`:1328`，`model/pdf_model.py:5202`、`:5220`、`:5225`。 |
| 哪些操作走整份快照 | 合併、刪頁、移頁、旋轉、校正歪斜、插空白頁／外部頁，見 `controller/pdf_controller.py:2274`、`:3206`、`:3233`、`:3262`、`:3301`、`:5994`、`:6042`。螢光標記與線標記、矩形、物件移動／旋轉／刪除／縮放／插圖、跨頁移動文字、metadata、目錄及註解新增／修改／移動／刪除，也走整份快照。見同檔 `:2960`、`:3322`、`:3352`、`:3939`、`:4033`、`:4081`、`:4128`、`:4169`、`:4196`、`:4936`、`:5766`、`:5851`、`:5879`。 |
| `AddTextboxCommand` | 首次執行新增文字框並擷取 after page graph。Undo／Redo 呼叫 `_restore_page_from_snapshot()`，由 `restore_page_graph()` 在原文件按 xref 寫回物件。它檢查 epoch、頁 xref 與 parent。同一頁稍後新增的 OCR 引用可在這裡消失，整份文件的還原 hook 完全收不到。見 `model/edit_commands.py:1157`、`:1178`、`:1194`，`model/pdf_model.py:5514`，`model/page_snapshot.py:271`、`:285`、`:320`。 |
| `EditTextCommand` | Tier 0／1 有 retained reversal 時，undo 用 inverse patch，redo 用 forward patch，並恢復原先記錄的 stream storage。一般單頁還原及已同意 rebuild 的 redo 使用 page graph。高保真 redo 缺 reversal 時會拒絕；沒有實際 replay outcome 的相容路徑可回到 execute。不可把 stale 拒絕改成無條件覆蓋單頁。見 `model/edit_commands.py:366`、`:508`、`:568`、`:599`、`:845`、`:916`、`:948`。 |
| 頁面替換、handle renewal、crop | 在查閱的產品程式中找到上述三個具體 `EditCommand`，未找到 `ReplacePageCommand`。合併的 forward path 走 `replace_active_document_from_snapshot(page_origins=...)`；straighten 則建立同尺寸新頁、畫入旋正後 raster、刪舊頁。repair／GC 也會換 handle，失敗 rollback 會共用整份還原 helper。這些事件不能一律當作一次 undo。未找到使用者裁頁命令；找到的 `set_cropbox()` 是表格偵測後復原幾何。獨立 crop UI 路徑為 **not verified**。見 `model/pdf_model.py:5231`、`:5251`、`:5262`、`:6357`、`:1329`，`model/table_objects.py:395`。 |
| `vector_delete` | 已有 model commit、快照 digest 欄位與 `verify_vector_digest()`。既有測試手工建立 `SnapshotCommand`，直接呼叫 `cmd.undo()`／`cmd.execute()` 後自行驗 digest。當前 Controller 的 undo／redo 成功分支只刷新 UI。B7 的生產接線仍待實作，不能把測試當作 UI 已涵蓋。見 `model/edit_commands.py:1261`，`model/pdf_model.py:4371`、`:4378`，`test_scripts/test_vector_delete_model.py:192`，`controller/pdf_controller.py:5228`、`:5250`。 |

**掛點決定。** 在 `CommandManager.undo/redo` 共用的內部交易中加入 model 提供的歷史執行器，涵蓋「命令執行前」到「允許移動 stack」兩端。整份與單頁 restore helper 只回報實際還原範圍。整份替換要檢查所有受管理頁；單頁 graph 若觸及共享資源，也要檢查受影響的其他受管理頁。不要在低階 restore 主動補寫，否則 vector rollback 會在檢查還原證據前看到新內容。[現有 vector rollback 順序](C:/Users/wilson/Documents/amam_pdf_editor/model/vector_paths/commit.py:241) · [Manager 成功後才移動 stack](C:/Users/wilson/Documents/amam_pdf_editor/model/edit_commands.py:1492)

### 2. OCR 目前寫入什麼

`_on_ocr_page_done()` 核對 job generation、active session，依回傳頁碼呼叫 `apply_ocr_spans()`，再清 worker snapshot cache。OCR worker 的輸入是先前擷取的文件 bytes，結果 bbox 是當時的視覺頁面座標。同一 session 在辨識期間換了頁序，現有兩項檢查都可以通過。[worker 快照與接收端](C:/Users/wilson/Documents/amam_pdf_editor/controller/ocr_coordinator.py:185) · [套用與 cache](C:/Users/wilson/Documents/amam_pdf_editor/controller/ocr_coordinator.py:269) · [辨識座標契約](C:/Users/wilson/Documents/amam_pdf_editor/model/tools/ocr_tool.py:243)

`apply_ocr_spans()` 逐筆 trim，略過空字／無效框，將 visual bbox 轉回 unrotated、裁至頁界，按文字選 `helv`／CJK 字型。字級為 `max(1, 0.9 × height)`，baseline 為 `(x0, y1 − 0.12 × height)`，傳入 `render_mode=3` 與當下 `page.rotation`。`insert_text_page_space()` 處理 `/UserUnit` 尺度後呼叫 `page.insert_text()`。每筆例外被捕捉並繼續；函式以呼叫未拋錯計數，沒有驗證內容完整性或所有權。成功後重建 block index、呼叫 `mark_page_content_dirty()`、增加一次 `edit_count`。[字型選擇](C:/Users/wilson/Documents/amam_pdf_editor/model/pdf_model.py:4190) · [逐筆寫入](C:/Users/wilson/Documents/amam_pdf_editor/model/pdf_model.py:4223) · [完成處理](C:/Users/wilson/Documents/amam_pdf_editor/model/pdf_model.py:4265) · [座標轉換](C:/Users/wilson/Documents/amam_pdf_editor/model/text_commit/transforms.py:452)

本機 PyMuPDF **1.27.1** 的 `Page.insert_text()` 使用 Shape，預設 `overlay=True`。Shape 安裝或重用字型，`commit()` 視需要平衡既有內容，再建立獨立 stream，將其加入 `/Contents`；原值若不是陣列，會建立陣列。**現行 OCR 沒有專屬 marked-content tag。** 本次記憶體實驗中，兩筆 OCR 把 `[5]` 變成 `[5, 7, 8]`，共用 `/helv` xref 6，原 stream bytes 相同；新 stream 含 `BT … /helv 12 Tf 3 Tr … TJ … ET`。不能假定所有 PDF 都只多一個尾端 xref。[Page.insert_text](C:/Users/wilson/Documents/amam_pdf_editor/.venv/Lib/site-packages/pymupdf/__init__.py:12599) · [Shape 字型](C:/Users/wilson/Documents/amam_pdf_editor/.venv/Lib/site-packages/pymupdf/__init__.py:15275) · [Shape.commit](C:/Users/wilson/Documents/amam_pdf_editor/.venv/Lib/site-packages/pymupdf/__init__.py:15832) · [/Contents 插入](C:/Users/wilson/Documents/amam_pdf_editor/.venv/Lib/site-packages/pymupdf/__init__.py:20355)

搜尋使用 `visible_search()` → `page.search_for()`。文字索引從 content-only `dict/rawdict` 產生 runs、paragraphs 和 fallback rows；點擊編輯使用這些 runs。實驗中兩筆不可見字得到兩個搜尋命中、兩個 indexed runs。Tier 0 的 `render_mode == 3` 規則會拒絕以該 show 為目標；這不會在 hit testing 之前排除它。建議本卡讓**本程式管理的新 OCR**可搜尋、選取及複製，但不作為真文字編輯目標。編輯索引可從下一節的基底頁建立，避免以 bbox 過濾時連正下方的原生文字一起排除。外來及舊版無標記文字沿用現行行為。[搜尋](C:/Users/wilson/Documents/amam_pdf_editor/model/tools/search_tool.py:30) · [索引來源](C:/Users/wilson/Documents/amam_pdf_editor/model/text_block.py:97) · [點擊入口](C:/Users/wilson/Documents/amam_pdf_editor/model/pdf_model.py:3344) · [Tier 0 拒絕條件](C:/Users/wilson/Documents/amam_pdf_editor/model/text_commit/plan.py:1757)

### 3. 頁面身分、版本與實體格式

| 項目 | 建議契約 |
|---|---|
| 頁面 key | `(session_id, logical_page_id)`。頁號、頁 xref、handle generation 及 frame 都不單獨充當身分。將現有 watermark 的 page-ID 演算法抽成 model 可用的共用邏輯。`origins` 使用一次即沿用原 ID，外部插頁、placeholder、同頁的第二份副本均配新 ID。新編號不隨 undo 倒退。 |
| 歷史保存哪些資料 | `DocSnapshot` 保存**該時刻的頁序 → ID 對照**。最新 OCR 內容與清除紀錄放在 session，絕不由歷史快照倒帶。merge 的 bare after bytes 也要補 page map。現有相鄰快照 dedup 只比較 bytes；若 bytes 相同但 page map 或其他附帶狀態不同，必須分開保留 metadata。 |
| 辨識與套用 | 建立 worker 快照時，同步記錄 `job_id, sequence, page_id, frame` 及來源頁的辨識輸入證據，例如同設定、排除註解的 raster digest。交付時依 ID 找頁，核對來源與 frame。已接受的 span 保存未旋轉 bbox、baseline、字級及**辨識時的文字方向**。重播不得把未旋轉 bbox 再反轉一次，或以當下 `/Rotate` 重算 baseline。 |
| 頁序與幾何 | move 跟 ID；delete 令該頁暫時無處可呈現，undo delete 恢復同 ID 時回到目前 OCR 版本；新頁不能繼承同位置舊頁。純顯示旋轉沿用已建立的原頁文字幾何，測四個直角。frame 包含解析繼承後的 MediaBox、CropBox 及原點、`/UserUnit` 與座標矩陣。crop 只在能證明變換且所有 glyph quad 仍適用時映射。無法證明時提示頁面與原因；若是歷史移動會令仍存在的頁面靜默失去已接受層，預設拒絕該步並維持原狀。straighten 是同尺寸換內容，應配新內容身分。 |
| 版本與生命週期 | 一頁一個 `Active(layer_id, version, payload_digest, payload)` 或 `Cleared`。第二次成功辨識原子替換整頁；重送同一結果、等值結果與空結果不改變目前層。複製頁在建立時複製當時有效層，取得獨立 ID。store 只保留當前 payload，已刪頁可在歷史仍能帶回時保留；trim、截斷 redo 分支後回收不可達頁。關閉 session 釋放 payload、tombstone 和待交付結果。容量不足在接受新版本前回報，既有層不得被靜默淘汰。 |

這些契約可沿用現有的 `origins`、snapshot sidecar 與單調 ID 配發。值得特別測試的是「刪除所有頁後的 placeholder」及「undo 插頁後在同位置開新分支」，兩者都容易把 OCR 貼到同尺寸的錯頁。[頁面重組入口](C:/Users/wilson/Documents/amam_pdf_editor/model/pdf_model.py:4780) · [watermark ID 對照](C:/Users/wilson/Documents/amam_pdf_editor/model/tools/watermark_tool.py:85) · [還原後的 ID 上限](C:/Users/wilson/Documents/amam_pdf_editor/model/tools/watermark_tool.py:405) · [merge sidecar](C:/Users/wilson/Documents/amam_pdf_editor/model/edit_commands.py:1073) · [快照 dedup](C:/Users/wilson/Documents/amam_pdf_editor/model/edit_commands.py:1604) · [placeholder](C:/Users/wilson/Documents/amam_pdf_editor/model/pdf_model.py:2616)

**實體格式建議。** 每頁每版建立一個只含 `3 Tr` 文字、擁有私有字型資源的 Form XObject。頁面以獨立 `/Contents` stream 呼叫該 Form；呼叫外包版本化的 `/AMAMOCR` marked content，記錄 layer ID、版本及 payload digest。資源名稱避開碰撞。共享或繼承的 `/Resources`、`/Contents` array 採 page-local copy-on-write；安裝不能改寫原生 stream 或兄弟頁資源。保留還原原有引用形態所需的資料。若需額外平衡 graphics state，必須能證明新增 wrapper 的範圍與可逆性。

`reconcile_ocr()` 解析 PDF operator 和有效資源引用，核對**實際執行次數、Form 型別、文字內容、字型依賴及 digest**。同版且恰一次就零寫入；缺少則新增；舊版或重複版只移除已驗明的呼叫與本頁私有引用，再裝目前版；`Cleared` 移除所有已驗明的舊版。共享物件仍有引用時保留。來源有相同字串、相同 bbox、其他 `3 Tr`、註解或孤兒 xref，均不能據此認領。已知原有管理層但解析不完整、marker 與內容矛盾、或已與第三方操作混合而無法安全拆分時，停止交易並報告。**舊版無標記 OCR 無法可靠回溯辨認**；本卡的替換／清除保證從首個可驗證的受管理版本開始。

### 4. 文字、向量與原子性

**文字 patch 的舊指紋需要完整保留。** `page_fingerprint()` 涵蓋所有內容 stream 的 xref 與 decoded bytes、字型依賴、marked-content 依賴、幾何、註解及其他繪圖狀態。`apply_patchset()` 在寫前重新比對；xref relocation 也只接受可證明的重新編號。本次實驗確認，原 stream 完全相同，加 OCR 仍會改指紋。僅將 OCR 放到獨立 Form 也一樣。[指紋內容](C:/Users/wilson/Documents/amam_pdf_editor/model/text_commit/inspect.py:769) · [寫前拒絕](C:/Users/wilson/Documents/amam_pdf_editor/model/text_commit/patch.py:157) · [relocation 條件](C:/Users/wilson/Documents/amam_pdf_editor/model/edit_commands.py:683) · [版本固定理由](C:/Users/wilson/Documents/amam_pdf_editor/CLAUDE.md:3)

建議為 **retained history replay** 加一條可驗證的基底路徑：

1. 在原生命令首次提交時，保留現有 live prepare／commit 驗證。同時在保留 xref 編號的隔離副本上，只解開已驗明的本程式 OCR 呼叫與私有資源，據此記錄 **before／after 基底**的 patch pair、指紋、relocation 證據與目標 stream 原始 storage。命令建立時若尚無 OCR，現有證據就是基底證據。
2. 重播時在隔離候選文件上做相同投影，再執行既有 fingerprint、expected bytes、splice、storage 與 relocation 驗證。不得在重播當下拿現況重簽 expected fingerprint。任何非 OCR 的字型、鄰接 stream、註解、幾何或不明 marker 被修改，仍應得到相同 stale 拒絕。
3. 命令成功後，在候選文件上合成**目前** OCR 版本，驗證只新增宣告過的 OCR 差異，再發布。這同時涵蓋「先文字編輯才 OCR」和「先 OCR、文字編輯、再重跑 OCR」。小型 Form 實驗證明解除呼叫及還原對應資源後，可回到原頁指紋；共享資源、CJK、renumber 及實際 Tier 1 全流程為 **not verified**，列為實作前段的決行測試。

**向量使用另一組明確的驗證對象。** `vector_delete` 的 T0／T1 保持對當時**整份實體文件**取樣，可能已含某一版 OCR。Undo 還原原始 before、redo 還原原始 after，先對相應表執行 `verify_vector_digest()`；通過後才能替換成目前 OCR。最後驗證這次 OCR 宣告的物件、資源與頁序差異，以及各頁有效層。完成合成後的整份 digest 可以不同於歷史 T0／T1。`equivalent()` 只處理既有 container 差異，不能為 OCR 略過任意物件。原始 digest 不符時保留 vector latch，不補寫、不發布成功。[現有 commit](C:/Users/wilson/Documents/amam_pdf_editor/model/vector_paths/commit.py:214) · [等價判定](C:/Users/wilson/Documents/amam_pdf_editor/model/vector_paths/commit_state.py:500) · [驗證與 latch](C:/Users/wilson/Documents/amam_pdf_editor/model/pdf_model.py:4378) · [B6 歷史設計](C:/Users/wilson/Documents/amam_pdf_editor/plans/b6-commit-design-astra.md:57)

**發布順序。** 在同一個綁定 session 的 write lease 內，依序執行「檢查 stack 頂端 → 建立候選文件及命令暫存狀態 → 還原／重播 → 驗命令 → reconcile → 驗 OCR → 發布文件、命令狀態及 stack」。保護範圍包括 `_applied`、`_tier0_active`、relocated patch pair、page map、maintenance book、placeholder、saved marker 與 `rewound_since_saved`。只回滾 PDF bytes 會留下下一次不能正確重試的命令。候選失敗即丟棄；若實作採原地寫入，須先具備可驗證的完整 rollback，rollback 失敗沿用 damaged-session 路徑。Revision 維持單調，失敗不假造歷史成功。[文字命令會改自身狀態](C:/Users/wilson/Documents/amam_pdf_editor/model/edit_commands.py:814) · [歷史 revision](C:/Users/wilson/Documents/amam_pdf_editor/model/edit_commands.py:1481) · [損壞處置](C:/Users/wilson/Documents/amam_pdf_editor/model/pdf_model.py:1329)

發布後使變更頁的文字索引、worker/search snapshot、已驗證文字候選、vector selection/index 失效，依最終文件重建或 lazy rebuild。整份替換必須涵蓋非當前頁。OCR 在 lease 期間到達，只按 `(session_id, job_id, sequence)` 排隊；釋放後重新核對頁身分與來源，再以獨立 OCR 交易套用，保留 redo 分支。現行 vector index 已綁 `handle_generation + content_revision`，可沿用失效機制。[文字 lazy rebuild](C:/Users/wilson/Documents/amam_pdf_editor/model/pdf_model.py:2116) · [vector cache](C:/Users/wilson/Documents/amam_pdf_editor/model/pdf_model.py:4397) · [搜尋 worker 快照](C:/Users/wilson/Documents/amam_pdf_editor/controller/search_coordinator.py:162) · [B7 lease 設計](C:/Users/wilson/Documents/amam_pdf_editor/plans/b7-design-astra.md:15)

### 5. 同頁衝突、儲存與清除

| 情境 | 建議行為 |
|---|---|
| 同頁原生文字編輯、註解、向量刪除 | 原生目標與 OCR 支持的區域無交集時，保留 OCR，undo／redo 後每個 OCR span 仍恰一次。不能用「全頁內容 hash 變了」作為永久丟棄條件。若操作更換、移走或遮除了 OCR 對應的來源內容，預檢列出受影響區域；能證明無關的 spans 保留。無法證明相容且會把舊文字貼到新內容時，預設拒絕該步並提示先清除／重辨。 |
| 真正 redaction | 被遮除文字不得從 store、舊 snapshot 或較晚交付的 worker 復活。建議在**執行 redaction 的同一筆成功交易**撤銷相交 spans 並留下獨立於歷史的清除紀錄；無法分辨時採整頁。Undo redaction 不自動還原已撤銷 OCR。若在 undo redaction 後重新辨識，再 redo 會碰到新文字，需在 redo 寫前處理衝突，不可先發布舊快照再補字。現有文字、物件操作確有 `page.apply_redactions()`；不能只攔 UI 命令名稱。`apply_pending_redactions()` 的實際工作則是 `clean_contents()`。見 `model/pdf_text_edit.py:2984`，`model/pdf_object_ops.py:1954`，`model/table_objects.py:625`，`model/pdf_model.py:5572`。 |
| Dirty 與 `edit_count` | 現有 `session_has_unsaved_changes()` 看 transferred dirty、command saved marker、tools dirty；OCR 只增加 `edit_count` 就無法表達 OCR-only 未存檔。增加 `saved_ocr_state` 與目前有效 OCR 狀態的比較，納入 session dirty。首次接受、真正替換／清除各增加一次 `edit_count`；純歷史補層、重送與 no-op 不增加。歷史 undo／redo 維持目前 marker 比對語意，save 成功才更新兩個基準並把 `edit_count` 歸零。見 `model/pdf_model.py:810`、`:1437`、`:6978`，`model/edit_commands.py:1549`、`:1698`。 |
| Save／Save As | 存的是已合成文件。受管理 OCR 寫入不能沿用目前的 `mark_page_content_dirty()`：它會撤銷 fidelity protection、排入 `clean_contents()`，之後可能改寫原生 stream 或合併 marker。對已有其他 pending maintenance 的頁，須在隔離副本上取下受管理層、執行原本允許的維護，再裝回並驗證；保留既有保真、加密、簽章及 secure-save 規則。存檔失敗不更新 OCR saved state。見 `model/pdf_model.py:1487`、`:5585`、`:6850`、`:6877`、`:6927`。 |
| Reopen／關閉 | 同 session 儲存後保留 store，因為較舊的命令仍可 undo。重開是新 session，檔中的 layer 已可搜尋；第一次替換、清除或建立需要 OCR 證據的歷史前，從可驗證的 Form 收編為已儲存基準，避免開檔即重插。無標記的外來層保持原樣。Detach 到新視窗同樣從移交 bytes 建立身分，並保留原有 dirty 語意。見 `model/pdf_model.py:832`、`:2038`、`:4861`。 |
| 明確清除 | 建議最小 UI 為「清除此頁本程式建立的 OCR」。原子解除該頁所有已驗明的呼叫、寫入 `Cleared`、清除搜尋 cache，保留其他文字與 redo。此後 undo 舊命令不能復活它。若 UI 延後，model 的 clear／tombstone 仍需先實作，以支援替換與 redaction。對「安全移除」另驗磁碟輸出沒有可回收的舊 OCR payload。 |

### 6. 替代方案

| 方案 | 判斷 |
|---|---|
| 僅在整份 restore 後掃 marker、呼叫現行 `apply_ocr_spans()` | 淘汰。漏單頁 graph，也無法讓已被 fingerprint 拒絕的 undo 成功。逐筆重寫還會重增計數、改 maintenance book。 |
| OCR 僅作 UI overlay，儲存時才寫進 PDF | 可以讓基底歷史簡單很多，但目前搜尋 worker、複製、移交、匯出及外部 PDF reader 都依賴實體文字層。採此案必須另建一致的合成讀取／輸出路徑，也會改變 `apply_ocr_spans()` 後可立即用 `page.get_text()` 搜到文字的既有契約。[現有搜尋驗收](C:/Users/wilson/Documents/amam_pdf_editor/test_scripts/test_ocr_model_insert.py:51) · [worker／移交快照](C:/Users/wilson/Documents/amam_pdf_editor/model/pdf_model.py:4855) |
| 所有命令重寫成只還原被編輯物件 | 可減少整檔覆蓋，但共享資源、頁樹、跨頁操作、annotation graph 與既有 vector 全文件驗證都要重新定義；單靠局部還原仍解決不了同頁文字指紋。超出本卡。 |
| 每頁一個 `ocr_page` command | 業主已排除。除了讓 Undo 撤掉 OCR，在 `undo → OCR → redo` 中，`record()` 還會消除 redo 分支。 |

## Evidence

- `git status --short --branch` → exit 0。分支為 `feat/true-text-edge-cases`，審查前後工作樹列項相同。
- `.venv\Scripts\python.exe -B -X utf8 -`，記憶體 PDF、兩次真實 `insert_text_page_space()` → 原 stream bytes 相同、page fingerprint 改變、`SearchTool` 命中 2、`TextBlockManager` 有 2 個 runs；還原先前 page graph 或整份 bytes 後，兩者命中均變為 0。
- 同環境，原生文字頁加帶隱形文字的 Form → 搜尋命中 1、原 stream raw bytes 相同、整頁指紋改變；測試副本解除 Form 呼叫並還原原資源後，原指紋相等、OCR 命中 0。此實驗只驗最小 fixture。

## Not performed

依唯讀設計審查範圍，未改檔、未跑 pytest、整套 CI 或 GUI。下列紅燈是待實作的驗收規格。正式 marker 格式、故障復原、共享資源、secure save/reopen、跨引擎畫面與大型文件記憶體峰值均為 **not verified**。

## Fence log

本卡不變更 vector Rule B、`equivalent()` 正規形或第三方 OCR 的所有權。未提出新的裁頁工具。

## Verified

已用實際頁面反證「只要原文字 stream bytes 不變，舊文字 patch 就能 undo」，也已反證「所有會丟 OCR 的還原都經過整份文件 helper」。兩個反例決定了下列實作順序。

### 紅燈優先順序與工作量

估計 **七個可獨立驗收的步驟**。第 3 步的原生文字 replay 與第 5 步的交易失敗復原是主要工作量；兩者未通過前，不宜把本卡當成單一 restore callback 上線。

| 順序／層 | 先寫且必須看到失敗的測試 | 實作位置 |
|---|---|---|
| 1 · Model／現況反例 | 兩頁各放唯一 OCR 字串。`edit(A) → OCR(A,B) → undo → redo → undo`，每步檢查原命令效果、stack 頂端與兩頁各命中一次。另跑 `undo → OCR → redo`、同頁 `AddTextboxCommand`。用真 PDF；只替代辨識結果。 | 新 `test_scripts/test_ocr_history.py`；`model/edit_commands.py`、`model/pdf_model.py` |
| 2 · Model／身分與實體層 | 重送同版、第二版取代第一版、clear 後還原含第一版的快照、同名外來 marker、損壞 Form、兩頁共享 resource／Contents。驗有效呼叫次數、外來文字、兄弟頁 raw bytes 與像素。 | 新 `model/ocr_layer.py`、`test_scripts/test_ocr_layer.py`；`model/pdf_model.py`、`model/tools/watermark_tool.py` |
| 3 · 文字保真 | 同頁兩種順序：`Tier 0/1 edit → OCR → undo/redo`、`OCR1 → edit → OCR2 → undo/redo`。要求實際命令成功、原生目標 raw storage 在相應方向正確、非目標 bytes／字型／位置不變。另竄改無關 stream 或 font，必須仍 stale、零寫入。驗 OCR 可搜尋、點擊下方原生字仍選對目標。 | `model/edit_commands.py`、`model/text_commit/patch.py`、`model/text_block.py`、`test_scripts/test_ocr_history.py` |
| 4 · 頁面與內容衝突 | move、delete/undo、刪到 placeholder、插頁後分支、merge 重複頁、四向旋轉、偏移 CropBox、`/UserUnit`、同尺寸 straighten。再測不相交文字／向量編輯、相交 redaction、undo redaction 後新 OCR 再 redo。逐頁驗字串、命中 bbox 及禁止復活的字串。 | `model/pdf_model.py`、`model/ocr_layer.py`、`controller/ocr_coordinator.py`、`test_scripts/test_ocr_history.py` |
| 5 · History／vector／故障 | 真實 manager 跑 `vector_delete → OCR(A,B) → undo → redo`，分別驗原始 T0/T1，再驗 OCR 合成差異與 vector index stale。注入 digest 不符、第一頁補好後第二頁拋錯、`update_stream` 寫後拋錯、索引重建失敗；比較舊文件、命令內部旗標、兩個 stack、book、dirty、可搜尋文字。重試只成功一次。另在驗證 yield 送入 OCR，斷言只於 lease 釋放後套用。 | `model/edit_commands.py`、`model/pdf_model.py`、`controller/pdf_controller.py`、`controller/ocr_coordinator.py`、`test_scripts/test_vector_delete_model.py` |
| 6 · 儲存／生命週期 | `clean → OCR-only dirty → save clean → undo dirty → redo 到 saved marker clean`；同一 marker 再套 OCR 應 dirty，純補層不加 `edit_count`。測失敗 save、儲存後仍 undo、更換 session、close/reopen、第二次 OCR、clear 後 secure save。用新開的 `fitz.Document` 查文字與命中數。 | `model/pdf_model.py`、`model/ocr_layer.py`、`test_scripts/test_ocr_model_insert.py`、`test_scripts/test_ocr_history.py` |
| 7 · Controller／真實介面 | 經頁面操作、Ctrl+Z／Redo、實際搜尋 worker、Save／Reopen 驗兩頁結果、標題 dirty 與無重複命中。用相同 DPI 比較 OCR 前後畫面，另比較真正文字編輯的目標與未改鄰字；記錄大型檔的峰值記憶體與 H22 heartbeat。 | `test_scripts/test_ocr_controller_flow.py`、`test_scripts/test_search_worker_flow.py`、受 `scripts/verify_supervise.py` 監督的 GUI driver |

### 風險與業主待決事項

1. **幾何與內容衝突。** 建議純旋轉正常通過；原頁已刪除時保留休眠資料；仍存在但無法安全定位時，拒絕該歷史步驟並指出頁面。請確認是否接受這個取捨，或允許明示「此頁 OCR 暫停」後繼續。後者會縮小「成功 undo 後仍可搜尋」的保證。
2. **Redaction 優先權。** 建議真正遮除時永久撤銷相交 OCR；若歷史 redo 會與後來新接受的 OCR 衝突，預設保留目前狀態並要求處理。此處需要業主確認，因為「成功遮除敏感文字」與「無條件保留可搜尋文字」在同一區域不能同時成立。
3. **管理範圍。** 建議新受管理 OCR 可搜尋／複製、排除於真文字編輯目標；第二次辨識採整頁替換。請決定「清除此頁 OCR」是否隨本卡提供 UI。舊版與第三方無標記隱形文字不能承諾精準清除。
4. **成本決行點。** 隔離候選文件、CJK Form 及指紋驗證會增加記憶體與延遲。先以第 3、5 步證明真實 replay、共享資源隔離與失敗可重試，再量大型檔。若成本超出既有 H22 要求，縮小候選副本的製作範圍；保留文字指紋、vector digest 與成功後 OCR 恰一次這三項驗收。
