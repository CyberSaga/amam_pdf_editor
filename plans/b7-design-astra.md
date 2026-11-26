# CAD 向量物件編輯設計審查

## Result

適用於 `feat/true-text-edge-cases`，已核對 HEAD 為 `4f608d04`。以下採用 2026-11-26 上午裁決。最重要的交易邊界是 **OCR 必須等到 `vector_delete` 的歷史命令記錄完成才可寫入**。若在 T1 結束便釋放寫入權，即使驗證通過，仍可能把 OCR 收進錯誤的快照，或在稍後 Undo 時抹掉。裁決與原設計見 `plans/owner-decisions-1124.md:54`、`plans/b6-commit-design-astra.md:54`、`plans/b6-commit-design-astra.md:57`。

## 1. H22 寫入管制、OCR 排隊與 Undo

### 共用寫入入口

在 `PDFModel` 增加不依賴 Qt 的 `DocumentWriteGate`。每個 Model 持有一個 gate，持有期間固定操作所屬的 session。這個層級也能攔住會暫時切換 active session 的操作。Controller 負責顯示忙碌狀態、送出進度與排程 drain。現有 `_live_only()` 只包部分 View slots，也刻意放行開檔、切頁籤與存檔；OCR bridge、CLI、timer 及 `main.py` 關窗另有入口。`edit_count` 和 `CommandManager.record()` 都發生得太晚，不能作為第一道 guard。見 `controller/pdf_controller.py:582`、`:617`、`controller/ocr_coordinator.py:156`、`main.py:273`、`model/pdf_model.py:746`。

| 時點 | 實作契約 |
|---|---|
| 取得寫入權 | 在第一個 snapshot、修改 tool state、改 history 或關閉舊 handle **之前**呼叫 `gate.begin(kind, session_id)`。一般寫入進行中也不得從巢狀事件迴圈啟動向量交易。將取得的 lease 明確傳給同一交易的內部呼叫。僅憑「同一個 UI thread」或一個可繼承的 `busy_depth` 放行，會讓重入的 slot 冒用外層權限。 |
| 涵蓋範圍 | Mode-entry 的 live／snapshot／live 驗證、commit 的 before、T0、寫入、T1、after snapshot、history publish，以及失敗時的 rollback 與驗證，都在同一 lease。向量 Undo／Redo 也從還原前持有到 stack 移動及對應 digest 驗完。現行 `commit_vector_plan()` 直接委派，`verify_vector_digest()` 尚未接受 `on_yield`。見 `model/pdf_model.py:4371`、`:4378`、`model/vector_paths/commit.py:118`、`:214`、`:237`。 |
| 事件泵 | 保留 H22 的 `>400 ms` 慢文件判定、每 50 ms 工作時間 yield、Controller 使用 `ExcludeUserInputEvents`，以及最長 heartbeat 間隔 1 s。最後一次 `on_yield(steps, steps)` 也仍持有 lease。每次返回時、重新讀取 live handle 前，核對 session、`handle_generation`、`content_revision`。慢文件不得因耗時被拒絕。見 `plans/cad-vector-object-editing-handoff.md:50`、`:53`、`model/vector_paths/commit_state.py:382`、`:389`。 |
| 意外外部變更 | 保留 H22 的最後防線。T0 發現外部 revision 變動，回 `VECTOR_SELECTION_STALE`，不還原。T1 發現已確認的外部變動，保留現場、停止比較、不裝 derived index、不記一般可 Undo 的 `vector_delete`，鎖住所屬 session 的向量編輯並回報「驗證中斷，變更已保留」。使用明確結果型別，避免落入現有一般例外的 rollback。普通的寫入驗證失敗仍走原本的 Rule B／rollback。見 `model/vector_paths/commit.py:216`、`:231`、`:236`、`test_scripts/test_vector_delete_model.py:170`。 |
| 釋放 | 成功發布或已驗證的 rollback 完成後，`finally` 釋放 lease。先交接已接受的 OCR，再開放下一筆互動寫入，避免 timer 插隊。每個 UI turn 最多處理一頁，頁內不重入。若還原失敗使 session damaged，保留尚未套用結果並顯示原因，不向不確定的文件自動寫入。 |

寫入點本身必須使用同一個 gate。Controller 可在開對話框或擷取快照前提早拒絕，Model、ToolManager extension 和 history 入口仍須驗權。這讓直接呼叫方法、worker completion 和 View signal 得到同樣結果。

### UI 執行緒寫入清冊

「可達」包含已排入的 Qt signal、timer、worker completion、程式直接呼叫 slot，以及它們觸發的內部方法。`ExcludeUserInputEvents` 會延後實體鍵鼠輸入，無法撤回這些已排入的呼叫。下表的 `C` 指 `controller/pdf_controller.py`，`M` 指 `model/pdf_model.py`。

| 操作與入口 | 泵內可達性與行為 | 已讀依據 `file:line` |
|---|---|---|
| OCR `page_done → apply_ocr_spans` | **可，延後套用**。worker 辨識、進度、取消與退休繼續運作。 | `controller/ocr_coordinator.py:89`、`:192`、`:269`，`M:4245`、`:4266` |
| Highlight、underline、strikeout、矩形，新增／修改／移動／刪除 note | 可由 queued view signal 進入。**拒絕整筆**，在 before snapshot 之前返回。 | `C:495`、`:541`、`:3317`、`:3341`、`:3929`、`:5845`、`:5879`、`:5925` |
| 註解顯示／隱藏 | 可。**拒絕**，還原 UI 勾選狀態。此操作會呼叫 `annot.set_flags()` 和 `annot.update()`。 | `C:547`、`:5939`，`model/tools/annotation_tool.py:570`、`:582` |
| 浮水印新增／修改／刪除與儲存時嵌入 | 可。互動寫入**拒絕**，包含只先改 session 浮水印清單的路徑。開檔取回已烘入的浮水印、存檔清除舊 embed，分別納入 open/save 的 lease。 | `C:561`、`:6360`、`:6376`、`:6386`，`model/tools/watermark_tool.py:131`、`:168`、`:206`、`:424`、`:475`、`:487` |
| 行內文字 Apply、空文字刪除、同頁編輯、跨頁文字移動、新文字框 | 可。**拒絕並保留編輯器輸入**。涵蓋 `CommandManager.execute()`、跨頁的 `edit_text → add_textbox` 和失敗還原；切換文件或關窗時 finalize editor 也走同一入口。 | `C:499`、`:512`、`:1898`、`:4617`、`:4878`、`:4926`、`:4954`、`:5102` |
| Redaction 與延後清理 | 可由文字／物件操作或 Save 間接到達。`add_redact_annot`、`apply_redactions`、`apply_pending_redactions`、`_maybe_garbage_collect` 只允許交易持有人執行。外部呼叫**拒絕**，連 `pending_edits` 也不能提前消耗。 | `model/pdf_text_edit.py:2984`、`model/pdf_object_ops.py:1953`、`M:5569`、`:5606`、`:5613`、`:5637`、`:6850` |
| 一般物件與圖片的新增、移動、旋轉、縮放、單筆／批次刪除 | 可。**拒絕**，批次不得先完成第一個物件。 | `C:515`、`:4015`、`:4075`、`:4110`、`:4141`、`:4164`、`:4185` |
| 頁面刪除、排序、旋轉、拉直、插空白頁、從檔案插頁、合併至目前文件 | 可。**拒絕**，包括頁面身分重排、replacement handle 與 history。另存合併副本若需讀取 live source，適用下方快照規則。 | `C:2242`、`:2269`、`:2288`、`:3200`、`:3227`、`:3257`、`:3287`、`:5989`、`:6031` |
| Metadata、TOC／書籤編輯 | 可。**拒絕**；單純跳至書籤可使用已發布的畫面。 | `C:485`、`:548`、`:549`、`:2951`、`:5755` |
| Undo、Redo、另一筆 vector commit／選取／索引安裝 | 可。新命令、history 移動及取代目前 selection token 一律**拒絕**。已完成的 scan answer **延後交付**，交付時重驗 session、handle、revision、page。只有持有 lease 的向量交易可發布自己的 derived index。 | `C:525`、`:5216`、`:5240`，`M:4361`、`:4397`、`:4458`，`controller/vector_edit_coordinator.py:251`、`:406` |
| Save、Save As、關閉前存檔、存其他頁籤、handle renewal | 可。**拒絕**，在清理頁面、寫磁碟、標記已儲存或切換 active session 前返回。 | `C:486`、`:2599`、`:2989`、`:6405`，`M:746`、`:870`、`:5849`、`:6850` |
| 開檔、切／關閉／拆出／接收頁籤、關窗與釋放 Model | 可。互動切換或移交**拒絕**；`closeEvent` 先 `ignore()`，保留視窗。外部 CLI 開檔、最佳化完成後自動開副本、已接受的關閉請求**延後**。在 `main.py` 的最終 release 也防止提早 `model.close()`。不同視窗的獨立 Model 可繼續工作。 | `C:1968`、`:1984`、`:2061`、`:2136`、`:2490`、`:2770`、`:2839`、`:2905`、`:6443`，`view/pdf_view.py:7732`、`main.py:273`、`:326`、`:408` |
| Search、OCR 啟動、print、optimize、export、文字預覽、render／thumbnail／snapshot | 已取得不可變 bytes 的 worker 可繼續。**延後針對 live handle 的序列化或複製**；OCR 新啟動可取向量交易開始前保留、綁定該 session 的唯讀辨識快照。禁止把 T0、T1 之間的文件交給 worker。尤其帶浮水印的 render 會以 live doc 為 `insert_pdf` 的 source，畫面重繪應使用舊 pixmap 或獨立快照。 | `C:1155`、`:1475`、`:2441`、`:3314`、`:5443`、`:5959`、`:6270`，`controller/search_coordinator.py:162`、`controller/print_coordinator.py:279`、`model/tools/manager.py:269`、`:276`、`model/table_objects.py:266` |
| 延後建文字索引、物件／表格／圖片掃描、verified scan／文字預覽結果、sidebar 與失敗重試 | timer 和 completion **可達**。純進度及不碰 live doc 的 worker-local cache 可繼續；依賴當前頁面的結果**延後發布或按舊 key 淘汰**。對 live page 的 lazy rebuild、讀取文字及重新產生快照也延後，因為旋轉頁面的文字擷取會暫寫 `/Rotate`。 | `C:1736`、`:3737`、`:5519`、`:5574`、`:6236`、`:6333`，`controller/object_probe_coordinator.py:366`、`:491`、`:514`、`controller/scan_verifier.py:181`、`model/page_content_text.py:76`、`:92` |

對清冊本身加一個紅燈：由 `activate()` 的 signal targets、各 coordinator completion、`QTimer`、CLI 及 window release 建立受測入口表。新入口若既未分類，也沒有「只讀已發布狀態」的依據，測試就列出方法名。另從 **公開 Model／tool 方法直接呼叫**一次，防止只有 Qt 外層包到 guard。現有訊號接線可從 `controller/pdf_controller.py:435`、`:477`、`:555` 查起。

### OCR 結果的生命週期與歷史規則

1. `page_done` 接受結果時，建立不可變 `PendingOcrPage(session_id, job_id, page_key, page_frame, sequence, spans)`。`spans` 是 `tuple[OcrSpan, ...]`，不保存 `fitz.Page` 或 QObject。`page_key` 在辨識快照建立時綁定邏輯頁面；至少一併核對 rotation、CropBox 與頁面身分。`handle_generation` 是檢查線索，成功 rollback 換 handle 後，須能用已還原的頁面身分重驗。僅憑頁碼相同不能套用。現有 snapshot 已攜帶工具的 page state。見 `utils/ocr_types.py:7`、`controller/ocr_coordinator.py:185`、`model/pdf_model.py:4761`、`:5202`、`:5223`。
2. 新增共用的 `submit_ocr_page()`，明確回 `Applied(count)`、`Deferred(id)` 或 `Stale`。`_on_ocr_page_done()` 與其他 OCR 寫入呼叫者都由此進入；現行回傳 `int` 的同步 `apply_ocr_spans()` 保留為取得寫入權後的實作。以 `(session_id, job_id, sequence)` 去重。FIFO 已接受結果在 worker 自然結束後仍有效；取消後拒收該 job 的新結果，已接受頁的處置與已立即套用頁一致。文件關閉、頁面已刪除或座標系已改變時明確淘汰，不能寫到新 active tab。見 `controller/ocr_coordinator.py:215`、`:269`、`:294`、`model/pdf_model.py:4200`。
3. **Undo 的建議規則是每個實際寫入的 OCR 頁各有一筆 `ocr_page` 命令。** 先記 `vector_delete`，再依序套用及記錄 OCR A、B。使用者按 Undo，順序為 B、A、向量；Redo 順序相反。這同時涵蓋排隊中和交易結束後才到達的 OCR。否則答案是**會抹掉 OCR**：`SnapshotCommand.undo()` 還原整份 `_before_bytes`，跨頁 OCR 也會消失。OCR 若在 vector Undo 驗證期間到達，驗完才記錄，依既有新分支規則清除 redo。見 `model/edit_commands.py:1319`、`:1328`、`:1441`、`:1459`。
4. 每頁的 before、寫入、索引／dirty 更新、after、history publish 是一筆原子操作。保留 `DocSnapshot` 的 maintenance book、xref epoch 與 page state。發布 history 建議先在暫存 stack 狀態完成 dedup、trim、redo 分支及 saved marker 計算，再一次換入。任一步失敗，回復文件與 history，已接受結果保留供明確重試；空結果不生空命令。`insert_text` 寫後拋錯也要納入故障注入，不能只依 `inserted` 判定是否已寫。成功後才確認佇列項完成、清 worker snapshot cache。現在 `rebuild_page()` 先於 revision tick，`record()` 又先 append 才 trim；兩處都能製造半完成狀態。見 `model/pdf_model.py:4245`、`:4256`、`:4266`、`model/edit_commands.py:1455`、`:1606`、`:1629`、`controller/ocr_coordinator.py:278`。
5. `vector_delete` 的 after capture 或 history publish 失敗，同樣在 lease 內回復，不先 drain OCR。`record()` 會推進 revision；若要沿用 derived index，在記錄後重綁，隨後真正寫入的 OCR 再依新 revision 失效。Undo／Redo 驗證使用各自的 before／after digest；Rule B 維持 live 文件的嚴格比較。見 `model/pdf_model.py:4397`、`:4410`、`model/edit_commands.py:1261`、`:1455`、`model/vector_paths/commit_state.py:500`。

## 2. 可點選的獨立圓頭點

**用一張按 `(path, subpath)` 排序的稀疏表保存點。** G 現在對 `m h` 保留暫存座標，F 也算出 `dpath/dx/dy`，但兩者都沒把點位置交給查詢。更直接的缺口是 `_click()` 先要求 `seg_count > 0`，而 G 的 `not self.prims` 分支又把多點 bbox 覆寫成第一個 `m`。因此只放寬 `_click()` 或只改 bbox 都不夠。見 `model/vector_paths/scan.py:869`、`:952`、`:974`、`model/vector_paths/scan_fast.py:996`、`:1109`、`model/vector_paths/index.py:149`，及 `plans/b5-fill-topology-clipped-design.md:30`。

| 項目 | 實作契約 |
|---|---|
| Schema 與成本 | `VectorIndex.dots` 使用 packed dtype `[("path","<i4"), ("subpath","<i4"), ("x","<f8"), ("y","<f8")]`，每點 **24 B**，座標是未旋轉頁空間。414,510 列、零個點時新增表的資料區為 **0 B**；1,000 點為 24,000 B；每列一點為 9,948,240 B，約 9.49 MiB。一列可有多點，實際上限按點數計。這些是 payload 推算，不含陣列標頭、建表暫存及資源解析資料。 |
| G／F 產生 | 由兩套 scanner 分別保存實際 subpath 編號；每個完全零長的 subpath 至多一筆。涵蓋 `m h`、隱式 close paint、同點 `l`、控制點全相同的 cubic。盲目將「端點相等」當零長，會誤收回到起點的非零曲線。裸 `m S`、fill-only、`n`、已知 butt／square cap 不產生可點圓點。保留既有 `seg_count`、`DEGENERATE`、byte span；已由點表處理的全零 subpath 不得再由普通 stroke distance 或 fill 邊界誤命中。 |
| 畫筆狀態 | G／F 都追蹤 `J`，預設 butt，`q/Q` 保存／還原。`gs` 可能改 `/LC` 與 `/LW`。遇到未解析的 `gs`，掃描端保留稀疏候選及其有效 `gs`／後續顯式覆寫來源；Model 安裝 index 時用該頁資源解析 `/LC`、`/LW`，產生可查詢的點集合與寬度。可解析且繼承 round cap 的點必須能點選；解析失敗不可猜成圓頭。純 bytes scanner 維持 D15，資源綁定跟隨 session／revision 失效。見 `model/vector_paths/scan.py:319`、`:725`、`:780`、`plans/cad-vector-object-editing.md:101`。 |
| bbox 與傳輸 | 取線、曲線控制點、所有圓點中心的聯集，再沿用向外取整；只有整列無幾何時才回退到 `pt0`。兩套 scanner 的 `dots.tobytes()` 與其他表逐位元組相等。把新表及必要稀疏附表加入 `nbytes`、child transport、payload 上限與累計配置額度。驗證 owner 範圍、排序、subpath、有限座標、count × itemsize；舊格式重新掃描，不能把「格式沒有 dots」當成「頁面沒有 dots」。見 `model/vector_paths/scan.py:1056`、`model/vector_paths/transport.py:41`、`:149`、`:198`。 |
| Click | 沿用 B5 stroke 點選容差 `r = max(tolerance, page_line_width / 2)`。點的精測為 `(px-x)² + (py-y)² <= r²`；該寬度是既有保守頁空間寬度。把點與一般幾何的命中依 **path 的繪製順序**合併，再取最高可選列；同一列的點和線只回傳一次。無 dots 的頁面直接走既有快速路徑。有 dots 時以排序表／向量運算取得候選，不為 414k 個 path 建 Python list，也不對每個 path 重掃整張點表。見 `model/vector_paths/index.py:139`、`:157`、`:182`、`model/vector_paths/scan.py:985`。 |
| 旋轉、全選與刪除 | Click 先經 `visual_to_unrotated_rect`，點不再次旋轉。疊圖輸出時才套 `_vector_visual_affine`。Touch 用點中心，contain 用整列構造 bbox，令現有以 contain 實作的 `all` 也能選到純點列。Delete 仍刪 parent path；混合列會一起刪除線與點。`plan_delete()` 已用 `EDITABLE` 選列並重掃輸出，不需為零 segment 製造假線。見 `model/pdf_model.py:4423`、`:4448`、`:4452`、`model/vector_paths/edit.py:74`、`:93`、`:103`、`:133`。 |

**像素驗收要選對 fixture。** 本次以 PyMuPDF 1.27.1 在記憶體建檔、重開、2× 灰階渲染。`1 J 8 w 20 20 m 20 20 l S` 確實有墨；單獨 `20 20 m h S` 的整頁則是白色。把 `m h` 與另一個同點 `l` 放在同一 paint，兩個位置都出墨，且沒有非零線段。以這一例驗證「有墨但現行選不到」及刪除後像素消失；另用 `m h S` 固定 B5 的構造點查詢語意，勿把白頁前後相同當成成功刪除的證據。

**50 ms gate** 從已安裝 index 的 `PDFModel.vector_select()` 入口計至 `VectorSelectionInfo` 返回。固定 CAD 樣本、座標及查詢順序，記每次耗時與最大值；測空白、密集區、點線重疊及只有不可編輯列的 click。另用稀疏點與每列一點的合成頁分辨退化原因。舊紀錄的 25 ms 是 median，不能證明新版本每次均 ≤50 ms。見 `plans/cad-vector-object-editing-handoff.md:344`、`plans/cad-vector-object-editing.md:420`、`plans/owner-decisions-1124.md:52`。

## 3. 放寬 `CLIPPED` 的可證明條件

**只有在有效裁切區可證明，而且整個上墨範圍嚴格位於其中時，才清除該列的 `CLIPPED`。** 同時保留裁切限制供目的地檢查。一個物件目前完全可見，平移後仍可能跨出同一個 clip；只改一個旗標便遺失這項限制。舊 B5 已指出 clip 的 bbox 無法證明菱形、環洞或文字裁切的內部。見 `plans/b5-fill-topology-clipped-design.md:47`、`:65`、`model/vector_paths/scan.py:963`、`:1006`。

1. **掃描狀態。** `clip_state = Unbounded | Rect(x0,y0,x1,y1) | Empty | Unknown`，使用未旋轉頁空間 float64。`q` 保存、`Q` 還原；`W/W*` 到終止 paint **之後**才與舊狀態相交。setter 本身仍是 `SETS_CLIP`。第一版只證明單一非退化 `re`、無其他 contour、建構時變換可證明一致，而且變換後四條邊確實與座標軸平行。負寬高、反射、精確 90° 旋轉可正規化。不能靠容許誤差把微斜矩形判為軸對齊。G／F 使用相同判準。見 `model/vector_paths/scan.py:730`、`:780`、`:800`、`:892`、`model/vector_paths/scan_fast.py:776`、`:795`。
2. **保守情形。** 多 contour、洞、曲線、菱形、shear 後的斜矩形、未知或有歧義的 text clip、無法確定建構 CTM 的 setter 都給 `Unknown`；後續已知矩形不能消除祖先的 `Unknown`。無交集為 `Empty`。兩者下方的列維持 `CLIPPED`。文字裁切在生效的 `ET` 更新；特別用巢狀 `q/Q` 加文字的案例防止漏判。見 `model/vector_paths/scan.py:751`、`:763`、`:791`、`plans/cad-vector-object-editing-handoff.md:560`。
3. **內含證明。** Fill 使用所有控制點與隱式閉合形成的保守外框。Stroke 再加有效筆寬、cap、join、miter limit 的外擴；可用 `half_width × max(√2, miter_limit, 1)` 作簡單保守界，`half_width` 包含 CTM 的最大奇異值。Combined paint 取兩者聯集。未知筆寬、無可靠界的 hairline、數值非有限或貼到邊界，都保留 `CLIPPED`。對墨跡外框向外取整，clip 向內取整。不可用中心線 bbox、曲線 chords 或 CropBox 覆蓋率取代這個證明。見 `model/vector_paths/scan.py:934`、`:985`、`:1056`。
4. **存證。** 對成功放寬的列保存稀疏 `clip_limits(path, rect_id, ink_bbox)`，共用相同有效矩形。只傳旗標不足以驗目的地；這些表也計入 transport 與 `nbytes`。移動資格表示「存在安全位移」。未來給定 `Δ` 時，`ink_bbox + Δ` 仍須嚴格位於同一有效 clip，且 clip 留在原座標。這是幾何前置條件，交易實作不在本稿範圍。
5. **像素 oracle。** 手寫兩份 fixture，一份保留 clip，一份只移除 clip；背景與相鄰物相同。對來源位置及獨立產生的安全目的位置，各自在 1×、2×、4× 重開、逐像素比較整頁。另用越界目的地、粗線中心線在內但墨跡越界、尖 miter、洞、巢狀窄 clip 作負控制。驗收時要求安全位置零差異、負控制確有差異且資格檢查拒絕。選取與刪除仍沿用構造幾何，裁切 setter 不能被連帶刪掉。現有基線見 `test_scripts/test_vector_index_queries.py:282`。

## 4. `skipped` 的精確遮罩

`select_counting_skipped()` 目前以全 1 遮罩跑幾何，再將所有 `~editable` 命中計數。應在選最上層或計算 marquee **之前** 排除 `n` 與 singular。這裡的「有可見 paint」採業主指定的 operator／flags 定義；`IN_OC` 也按此規則納入，不另做整頁像素可見性判斷。見 `model/vector_paths/index.py:56`、`:68`、`:76`、`model/vector_paths/scan.py:59`、`:981`。

```python
flags = index.paths["flags"]
editable = (flags & int(PathFlag.EDITABLE)) != 0
reasons = int(
    PathFlag.IMPURE | PathFlag.SPANS_STREAMS
    | PathFlag.IN_OC | PathFlag.SETS_CLIP
)
countable = (
    ~editable
    & ((flags & reasons) != 0)
    & ((flags & int(PathFlag.CTM_SINGULAR)) == 0)
    & (index.paths["paint"] != PAINT_NAMES.index("n"))
)
eligible = editable | countable
```

- **Touch／contain** 以 `eligible` 做一次幾何查詢。回傳 `hit & editable` 及 `int(np.count_nonzero(hit & countable))`。同列多原因只計一次。
- **Click** 在 `eligible` 中命中可編輯列，回該列與 `0`。若最高命中只有 `countable`，續找底下可編輯列；找到回該列與 `0`，找不到回空遮罩與 `1`。完全未命中回 `0`。任何 mode 的選取遮罩都必須等於 `select()`。點表共用同一遮罩。
- **其他入口** `summary()` 若收到含非編輯列的外部 mask，沿用同一 `countable`；`clear` 回 `0`。`all` 使用全頁幾何及同一計數規則。`skipped` 描述本次 query，`count`、`movable_count` 描述 combine 後的選取。見 `model/vector_paths/index.py:278`、`model/pdf_model.py:4443`、`:4457`。
- **紅燈矩陣** 四個原因各一列、四原因同列、`W n`、`W S`、單獨 singular、`singular | IMPURE`、`singular | IN_OC`、普通 `n`、`CLIPPED`／`PAGE_ANCHORED` 可編輯列。每種測 click、touch、contain；再測「不計數列蓋住可計數列」及「可計數列蓋住可編輯列」。既有測試主要固定 `IN_OC` 與 click 0／1 語意。見 `test_scripts/test_vector_index_queries.py:303`、`:312`。

## 5. 可移動子集與 View DTO

Model 在 `combine()` 後只算一次分類，供摘要、疊圖及日後的移動請求共用。現行 `supports_move` 只要選取含一個 blocker 就是 `False`；`vector_selection_segments()` 則已將所有選取線段攤平，View 無法從這個陣列辨認哪些列受限。見 `model/object_requests.py:119`、`model/pdf_model.py:4461`、`:4468`、`:4476`、`model/vector_paths/index.py:291`。

```python
selected = combined_mask & editable
blocked = int(PathFlag.CLIPPED | PathFlag.PAGE_ANCHORED)
movable = selected & ((flags & blocked) == 0)
fixed = selected & ~movable

count = int(np.count_nonzero(selected))
movable_count = int(np.count_nonzero(movable))
supports_move = movable_count > 0
supports_delete = count > 0
```

`CLIPPED` 取第 3 節放寬後的值。在 `VectorSelectionInfo` 尾端新增 `movable_count`，同步檢查所有建構點。`count`、總 bbox 和 Delete 仍涵蓋全部選取。例：選到普通線、實際被裁切的線、`PAGE_ANCHORED` 圓點各一個，結果應為 `count=3, movable_count=1, supports_move=True, supports_delete=True`。

**View 接收已分組的顯示幾何。** 在中立模組 `utils/vector_selection_dto.py` 新增 `VectorSelectionPresentation`，包含 `session_id, page_num, token, count, movable_count, skipped, visual_bbox, supports_move, supports_delete`，以及 `movable_geometry`、`fixed_geometry`。每組有唯讀、連續 float32 的 `segments[K,4]` 與 `dots[D,2]`，均為 visual page coordinates。Model 以同一個 token 產生兩組，Controller 核對 session／revision 後一次發布。View 不取得 `VectorIndex`、NumPy 選取遮罩或 `PathFlag`，也不匯入 `model`。舊 `vector_selection_segments()` 呼叫者可繼續取得原契約。見 `model/pdf_model.py:4488`、`test_scripts/test_vector_select_model.py:79`。

**訊號路徑**為 `PDFView.sig_vector_select → PDFController.activate()` 接線的 slot → `PDFModel.vector_select()` → `VectorEditCoordinator.selection_changed(object)` → `PDFView.set_vector_selection(presentation)`。`VectorEditCoordinator` 已是 `QObject`。View 用實線及實心點表示可移動，用虛線及空心點表示固定，差別不只靠顏色。clear、換頁籤、索引失效時移除舊疊圖；縮放重建場景時以同一 DTO 重畫。狀態列可顯示「已選 3 個，可移動 1 個」。見 `controller/vector_edit_coordinator.py:152`、`view/pdf_view.py:639`、`controller/pdf_controller.py:516`、`plans/cad-vector-object-editing-handoff.md:360`。

## Evidence

- `git rev-parse --short=8 HEAD` → `4f608d04`；`git diff --stat HEAD` → 無 tracked 差異。
- `.venv\Scripts\python.exe -B -`，PyMuPDF 1.27.1 記憶體建檔及重開 → 2× 下，round-cap 同點 `l` 有 216 個非白像素；純 `m h S` 為 0；`m h` 配另一個同點 `l` 為 432。混合 `m h` 與一般線段時，現行 G index 在有墨的點中心 click 回傳空選取。
- 同一方式比較有／無矩形 clip 的整頁灰階圖 → 來源與安全目的地在 1×、2×、4× 均為 0 個差異像素；越界矩形及中心線仍在內的粗筆畫，分別在三個倍率出現 32、128、512 個差異像素。

**Not performed**　依唯讀要求未改檔、未跑 pytest 或 GUI。新 schema 的實際 RSS、414,510 列產品點選耗時、H22 heartbeat、完整 UI 入口注入及跨 session 重播均為 **not verified**。

**Fence log**　範圍止於五項裁決。保留 copied stream 非純量參照的既有拒絕，以及 `equivalent()` 的現行用途。未設計 move transaction。

**Verified**　以程式碼反查「排到 T1 後即可安全 Undo」，找到 after snapshot 與 `record()` 的空窗；以渲染反查「中心線在 clip 內即可移動」及「純 `m h S` 可證明像素刪除」，兩者都有反例，已反映在交易邊界與測試 fixture。

## 紅燈優先的實作順序

每步先跑列出的失敗案例，保存實際 failing tail，再改該層；下列是待實作驗收，不是已通過的測試。

| 順序／層 | 第一個紅燈與驗收 | 檔案 |
|---|---|---|
| 1 · Model／Controller 寫入入口 | 在 T0、T1、最後一次 yield 各投遞 OCR、註解顯隱、Save、Undo、切 tab、帶浮水印 render。第一個 mutator、serializer、history 與 handle 變動計數都須為零；OCR worker 同時仍可報第二頁完成。加入直接 Model 呼叫與入口清冊檢查。 | `model/pdf_model.py`、`controller/pdf_controller.py`、`controller/ocr_coordinator.py`、`model/tools/manager.py`、`main.py`、新增 `test_scripts/test_vector_write_gate.py` |
| 2 · History／OCR | `vector_delete → OCR(A) → OCR(B) → undo×3 → redo×3`，逐步檢查向量、兩頁可搜尋文字、dirty、digest、stack。注入 rebuild、after capture、append／trim 後失敗、rollback 換 handle、自然 finished、取消、重複 delivery、Undo 驗證中收到 OCR。不可有半寫入、誤清 redo 或重複文字。 | `model/edit_commands.py`、`model/pdf_model.py`、`model/vector_paths/commit.py`、`controller/ocr_coordinator.py`、`test_scripts/test_vector_delete_model.py`、`test_scripts/test_ocr_controller_flow.py` |
| 3 · Scan／transport | 單點、多點、混合、三種 cap、`gs` 繼承、`q/Q`、非零閉合 cubic、強制批次切割。驗期望點數、座標、bbox、F/G bytes、傳輸 round-trip、錯誤 owner／count、配置上限。 | `model/vector_paths/{scan,scan_fast,transport}.py`、`model/pdf_model.py`、`test_scripts/test_vector_scan*.py` |
| 4 · Query／delete | 點在墨上、只點 bbox 空隙、點被較高 fill 遮住、dot-only 全選及 delete。四個旋轉角 × 有無 CropBox；刪除後重開與獨立 survivor-only 文件比較，新 index 的點 owner 必須正確。量產品 click ≤50 ms。 | `model/vector_paths/{index,edit}.py`、`model/pdf_model.py`、`test_scripts/test_vector_{index_queries,select_model,delete_plan}.py` |
| 5 · Clip 證明 | 安全矩形本應放寬；寬筆、尖角、負尺寸、巢狀交集、跨 stream、text clip、洞、shear、`Q` 後兄弟列、目的地越界。驗 F/G 一致、稀疏限制可傳輸，以及第 3 節像素 oracle。 | `model/vector_paths/{scan,scan_fast,transport}.py`、`test_scripts/test_vector_scan.py`、`test_scripts/test_vector_scan_fast.py` |
| 6 · Query／摘要 | 跑第 4 節 mask 矩陣；特別要求 `W n=0`、命中的 `W S=1`、`IMPURE \| CTM_SINGULAR=0`，以及選取遮罩等於 `select()`。 | `model/vector_paths/index.py`、`model/pdf_model.py`、`test_scripts/test_vector_index_queries.py` |
| 7 · DTO／Controller／View | 普通、受裁切、anchored 三列混選；逐步 add／toggle／clear，驗 count、動作 enable、兩組線與點、過期 token、縮放重畫。以真實視窗驗兩種樣式，再跑 600 ms sliced pass 與 heartbeat gate。 | `model/object_requests.py`、`utils/vector_selection_dto.py`、`controller/{pdf_controller,vector_edit_coordinator}.py`、`view/{pdf_view,vector_selection}.py`、`test_scripts/test_vector_select_model.py`、新增 GUI 測試 |

### 風險與需業主確認事項

- **逐頁 OCR snapshot 的時間與歷史預算。** 現有 trim 先淘汰最舊命令，大文件連續 OCR 可能使 `vector_delete` 提早離開 Undo 範圍。要量逐頁擷取耗時、最大 UI 停頓及實際可保留頁數。見 `model/edit_commands.py:1613`、`:1629`。
- **最容易漏測的兩類寫入**是表面唯讀的 live serialization／暫寫 rotation，以及歷史發布一半才拋錯。驗收須同時觀察底層文件、可搜尋文字、history、saved marker 與 handle，單查 `edit_count` 或最終畫面不足。
- **請業主確認的唯一產品語意**是「每個成功套用的 OCR 頁可獨立 Undo」。本稿建議採用，且已給出可直接實作的命令順序。若要求使用者一次 Undo 就撤銷向量刪除、同時留下其後全部 OCR，則需另定選擇性 Undo 或重播契約，現有整份文件 snapshot 無法直接達成。
