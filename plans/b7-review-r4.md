## Result

### Must-fix（依優先序）

1. **G4 的文件與 history 仍可分開發佈。** `record()` 已把 `lease.published` 設為 `True`，若 `with` 內下一行拋錯，`write_transaction()` 仍會執行 `undo_write`，把文件還原，卻保留刪除命令。另一條路徑是正常離開 `with` 後，第二次 `install_vector_index()` 拋錯，直接跳過 `lease.release()`，使後續寫入持續被拒。應由交易統一完成 history、索引重綁與發佈，失敗時一起復原，並在 `finally` 釋放 lease。另須處理復原本身失敗：目前 `_recover_unpublished()` 只記錄例外，正常離開的呼叫端可能看不到失敗。`model/edit_commands.py:1475`、`model/edit_commands.py:1483`、`model/pdf_model.py:4405`、`model/pdf_model.py:4413`、`model/pdf_model.py:4424`

2. **G1/G4 的 `undo_write` 可以還原到錯的 session。** 一般 tab、CLI 與 close 入口已有拒絕措施，目前的 vector commit／rollback 本身也不需要呼叫 `activate_session()`。但 `activate_session("B", write_lease=lease)` 會通過通用 gate。若先在 A 完成刪除，再以同一 lease 切到 B，未發佈便離開，closure 持有 A 的快照，restore 卻會關閉當下的 `self.doc`，將 A 的快照裝進 B。T0、T1 的 callback 返回也沒有重驗身分。應固定原 session、doc、handle generation、revision，每次 yield 返回先核對，rollback 只准作用在可證明屬於 A 的 handle。`model/write_gate.py:71`、`model/write_gate.py:165`、`model/pdf_model.py:805`、`model/vector_paths/commit.py:131`、`model/vector_paths/commit.py:219`、`model/vector_paths/commit.py:237`、`model/pdf_model.py:5397`

3. **G2 擋住了空 FIFO 的 latched OCR，但仍會接受辨識自舊影像的文字。** 我在記憶體內只替換掃描頁的 image XObject，實際像素已變，`ocr_source_key()` 卻完全相同，因為它只雜湊頁面 `/Contents`。`_ocr_sources` 又取自 live model，worker 收到的則可能是快取 snapshot；缺少 proof 時，`.get()` 回傳 `None`，還會退回到件時的幾何或直接寫入。應讓 worker 回傳實際辨識影像與座標框的證明，直接套用與 drain 共用驗證，缺證明的 worker 結果回 `Stale`。`controller/ocr_coordinator.py:190`、`controller/ocr_coordinator.py:197`、`controller/ocr_coordinator.py:283`、`controller/pdf_controller.py:1215`、`model/pdf_model.py:4427`、`model/pdf_model.py:4449`、`model/tools/ocr_tool.py:290`

4. **G3 已隔離 `vector_plan_inputs()` 的 mask，但相同 digest 仍可對應不同刪除範圍。** 對同一份雙路徑 index，實際呼叫 `plan_delete()`，布林 `[True, True]` 刪兩條，整數 `[2, 1]` 只刪第二條，兩份 `selection_digest` 卻相同。原因是計算範圍時對原陣列做位元 `&`，計算摘要時才轉成 `bool`。應在入口驗證 dtype，或只產生一次不可變的布林 mask，讓 ranges 與 digest 共用。另一路 `vector_selection_mask()` 仍把可寫的 live array 暴露在 `.base`，也應封住。`model/vector_paths/edit.py:39`、`model/vector_paths/edit.py:73`、`model/vector_paths/edit.py:80`、`model/vector_paths/edit.py:152`、`model/vector_paths/commit.py:95`、`model/pdf_model.py:4375`、`model/pdf_model.py:4569`

5. **G1 仍有 T1 可以觀察到未發佈文件的正式入口。** `jump_to_result` 在允許清單內，同步 fallback 會從 live doc 取 pixmap 並顯示；有效 `sid/gen` 的索引 timer 也能對 missing/stale 頁呼叫 `rebuild_page(..., self.doc)`。即使稍後 rollback，使用者也可能已看過刪除後的頁面。整窗一般 `closeEvent` 已正確遵守 `ignore()`，但 `destroyed` 或 promotion 直達 `_release_window()` 時，仍會先 retire workers、釋放 render owner，再嘗試 `model.close()`；promotion 還會先把次視窗移出清單。重設 released flag 無法復原這些副作用。`controller/pdf_controller.py:603`、`controller/pdf_controller.py:5200`、`controller/pdf_controller.py:5576`、`model/pdf_model.py:2137`、`view/pdf_view.py:7731`、`main.py:282`、`main.py:332`、`main.py:443`

6. **`commit_vector_plan()` 不傳 lease，確實能留下已改文件且沒有 history。** 這是既有 model API 的成功語意，現有測試也明確要求刪除生效。該分支只用 `write_gate.begin()`，沒有 transaction recovery 或 `record()`。接 controller 前，應讓正式入口持有 lease 直到發佈，避免省略參數就走到這條低階路徑。`model/pdf_model.py:4385`、`model/pdf_model.py:4394`、`model/write_gate.py:42`、`test_scripts/test_vector_delete_model.py:98`

### Should-fix（依優先序）

1. **把 busy 判定移到既有 activation FIFO 的隊首。** 現在先 `pop(0)`，每個 busy CLI 再各自排 100 ms timer。A 已被移出隊列後，解鎖時新到的 B 可以先執行；同一 FIFO 的 optimize completion 還可能遇到 `open_pdf()` 拒絕後直接失去開檔動作。保留隊首、共用一次重試即可維持順序。`controller/pdf_controller.py:2113`、`controller/pdf_controller.py:2195`、`controller/pdf_controller.py:2207`、`controller/pdf_controller.py:2549`

2. **保留並測清楚合法持有者的巢狀呼叫契約。** `open_pdf(..., write_lease=lease)` 開既有文件時會呼叫 `activate_session(existing_id)`；`save_session_as()` 儲存非目前分頁時也會經 `_activate_temporarily()` 呼叫它。外層 wrapper 已取走 `write_lease`，內層因此被自己的 gate 拒絕。應分清 lifecycle 操作的合法切換與 vector lease 固定 session 的要求。`model/write_gate.py:165`、`model/pdf_model.py:753`、`model/pdf_model.py:883`、`model/pdf_model.py:1913`

### 類別測試與復發判定

**七項 × T0/T1 不足以封閉第三輪的同類缺口。最明確漏送的是從第二個視窗 C 向正持有 lease 的 A 交接分頁**，目前只有直接呼叫 `adopt_transferred_session()` 的 mock 測試。Redo action 也沒送；Undo 直接呼叫 `c.undo()`，空 stack 可以提前返回；OCR 直接呼叫 handler，沒有走 worker bridge 或帶入來源證明。測試只在每一遍最後一次 callback 派送，沒有強制 pixmap fallback、觀察 index build 次數，或拿獨立串行結果比對。`test_scripts/test_vector_transaction_reentrancy.py:49`、`test_scripts/test_vector_transaction_reentrancy.py:60`、`test_scripts/test_vector_transaction_reentrancy.py:120`、`test_scripts/test_vector_transaction_reentrancy.py:141`、`test_scripts/test_vector_write_gate_controller.py:119`、`controller/pdf_controller.py:5268`

**能封閉這類復發的一項檢查，是「正式註冊的入口，必須實際送達，且結果等同串行執行」。** 從 View、Controller、coordinator、main 的 signal、timer、event 與 handoff 註冊點推導接收端；在兩窗 fixture 的 T0/T1 中途與末次 callback 逐項送達並取得確認。每次返回核對身分及禁止的副作用，最後對照成功或故障的串行基準，比較各文件內容、history、selection 與 OCR FIFO。現有 AST 只收集 `singleShot` 所在函式；在同一函式加第二個 timer，集合仍相同，也沒有任何斷言要求該接收端出現在 `_fire()`。這正是第三輪指出的「清單通過，實際入口漏掉」。`test_scripts/test_vector_transaction_reentrancy.py:220`、`test_scripts/test_vector_transaction_reentrancy.py:237`、`test_scripts/test_vector_transaction_reentrancy.py:245`、`plans/b7-review-r3.md:38`、`plans/b7-integration-design-astra.md:22`

**Evidence**　基準為 `feat/true-text-edge-cases`、`ad4d79c6` 加工作樹。`git diff HEAD --check` 通過。  
**Not performed**　依要求未跑 pytest、Qt 或 benchmark；未將執行中的 suite 計入證據。  
**Fence log**　全程唯讀。  
**Verified**　以工作樹交易方法搭配替身注入兩個發佈邊界故障，分別觀察到文件回復而 history 保留、以及 lease 未釋放。另用真實記憶體 PDF 和實際 `plan_delete()` 分別確認 OCR 與選集摘要反例。

**判定：目前接上內部 `vector_delete` controller 流程仍不安全。** 即使 controller 一律傳入正確 lease，發佈後例外、索引重綁失敗及 T1 的 live reader 仍直接影響這條路徑。應先讓文件與 history 在故障時維持一致，固定復原對象，並讓兩窗實際派送的串行比對涵蓋上述反例，再接內部流程。


## Recurrence
- This round: boundaries of the transaction that the new class test and admission guards still do not cover (publish split between history and document, rollback target identity, OCR proof not covering image content, selection digest dtype, T1 live readers, low-level commit_vector_plan without a lease).
- Previous round: entries and lifecycle paths outside the gate, publish boundaries (round 3 items 1-5).
- Same mechanism: yes (the transaction boundary is still not one object: publish, rollback target and live readers recur; the dtype digest and OCR image proof are new instances of identity not bound to the data it protects).
- Class fix: make the transaction a single object that owns document, history, index and lease, and prove it by an outcome comparison against a serial baseline with fault injection at every step; derive entries from registrations (receiver must appear in the test's fire table) instead of from timer sites. Not patched yet: owner decides (plans/b7-integration-gaps.md).
