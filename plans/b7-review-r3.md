## Result

**第三輪判定：一般分頁關閉已受保護，整窗退出仍可能只完成一半的清理。正式啟用 `vector_delete` 前，還需要封住跨分頁寫入、受損文件的 OCR 直寫，以及刪除計畫與選取不一致這三條路徑。**

### Must-fix（依優先序）

1. **禁止在 T0／T1 讓出事件迴圈時切換交易文件。** 轉送 CLI 開啟另一個已開啟的檔案時，`open_pdf()` 直接呼叫 `_switch_to_session_id()`，完全跳過新加的 `PDFModel.open_pdf` guard。`activate_session()` 可以切到 B；commit 仍持有 A 的 `doc`，但後續的 `edit_count`、derived index 及 rollback 都經由當下的 active model。結果可能是刪除寫進 A、歷史記進 B，失敗時甚至用 A 的快照復原 B。應在切換入口拒絕，並在每次 yield 返回後核對原 session、handle、revision。允許通行的 `jump_to_result()` 也仍可讀取尚未發布的 live pixmap。`controller/pdf_controller.py:2106`、`:2022`、`:2014`、`:601`、`:5178`；`model/pdf_model.py:802`；`model/vector_paths/commit.py:93`、`:126`、`:214`、`:222`、`:242`

2. **整窗關閉應在接受事件及取消工作前處理 busy。** 一般分頁關閉（含 `Ctrl/Cmd+W`）只發出 signal，`_live_only` 會在進入 `on_tab_close_requested()` 前拒絕。整窗的 `closeEvent()` 卻直接呼叫 `handle_app_close()`；乾淨文件可被接受並發出 `closed`。此時 `_release_window()` 已設 `_window_context_released = True`、退休背景工作，才在 `model.close()` 遇到 `WriteGateBusy`。後續清理會因旗標而略過，文件與檔案鎖可能留存。應在 `handle_app_close()` 最前面 `event.ignore()` 或延後重試，並讓清理失敗後仍可重入。跨窗匯入也應先檢查目標視窗的 gate，目前匯入遭拒前已結束 editor、取消 reader。`view/pdf_view.py:1545`、`:1551`、`:7729`；`controller/pdf_controller.py:482`、`:670`、`:2816`、`:2826`、`:6478`、`:6539`；`main.py:280`、`:286`、`:408`

3. **`lease.published` 修好了正常出口的判斷，尚未保證文件與 history 同時發布。** `commit_vector_plan()` 回傳 `None`、呼叫端直接離開 `with`，現在確實會保留 OCR。但成功刪除後，若 after-capture 失敗，`write_transaction()` 只釋放 lease；若 `record()` 的 dedup／trim 失敗，revision 和 undo stack 已改。反方向上，`published` 又早於清除 redo。應在同一 lease 下恢復文件與 history，或明確鎖住無法驗證的 session。成功時也要在 `record()` 後重綁 derived index，否則剛安裝的 index 會立刻因 history revision 改變而失效。`model/pdf_model.py:4400`、`:4509`、`:1453`；`model/edit_commands.py:1462`；`model/vector_paths/commit.py:228`

4. **latched session 的空佇列仍會寫入 OCR。** FIFO 在已有待處理頁時成立，`drain_pending_ocr()` 也確實檢查 latch。但 gate 已釋放且佇列為空時，`submit_ocr_page()` 直接呼叫 `_apply_ocr_now()`，完全不看 `vector_editing_blocked`。現有 latch 測例先塞入一頁，剛好避開此分支。另一路風險是 worker 只送 `gen, page_num, spans`，page key 到交付時才從 live doc 取得；同一 session 在辨識後換頁內容，舊文字仍可能寫進新頁。直接與排隊入口應共用 latch 與來源頁驗證，來源身分須隨辨識快照傳回。`model/pdf_model.py:4413`、`:4421`、`:4428`、`:4443`；`controller/ocr_coordinator.py:90`、`:194`、`:271`；`test_scripts/test_vector_write_gate.py:420`、`:433`

5. **刪除計畫必須綁定使用者看到的選取。** `_live_vector_selection()` 已能拒絕被換掉的 index，mask、segments、presentation 都有使用它。但 `vector_selection_mask()` 只將 view 設為唯讀，底層仍可寫；`vector_plan_inputs()` 更直接交出原始 mask。現成反例就在測試中：先選 `all`，另造只含第二列的 mask，用原 token 建立計畫，commit 仍成功。應交付獨立或不可變的 mask，並讓 plan 攜帶可與該 token 核對的選取身分。否則即使 UI 顯示正確，刪除範圍仍可能不同。`model/pdf_model.py:4375`、`:4515`、`:4526`、`:4592`、`:4614`；`model/vector_paths/edit.py:27`；`test_scripts/test_vector_write_gate.py:285`、`:301`

6. **補上 inventory 已知漏掉的實際寫入入口。** `writer_candidates()` 只掃三個具名類別，沿 `self.method()` 追蹤，遇到位置參數 `helper(self)` 只記下呼叫名稱。它看不到 `helper(doc)`、`helper(self._model)`、關鍵字傳參、獨立呼叫的 free function、繼承方法或 `ToolManager` 的動態派送。具體而言，`WatermarkTool.on_session_open()` 可經 `strip_marked_watermarks()` 寫入 stream；正常 open/import 有外層 guard，但直接呼叫 hook 沒有。`pdf_object_ops.add_textbox(model, …)` 也能直接寫。`NOT_A_WRITE_ENTRY` 又按裸方法名豁免，甚至把有 setter、能更換 live handle 的 `doc` 描述成 accessor。應以類別、方法及實際寫入路徑分類，並對這些入口加入持有外部 lease 時的行為測例。`test_scripts/test_vector_write_gate.py:445`、`:455`、`:471`、`:495`、`:505`；`model/write_gate.py:137`；`model/pdf_model.py:898`、`:2024`、`:2114`；`model/tools/watermark_tool.py:137`、`:168`；`model/tools/watermark_rendering.py:212`；`model/pdf_object_ops.py:1418`

### Should-fix（依優先序）

1. **讓 cache 測例能抓到漏算，並在安裝時固定來源資料。** `warm()` 確實先建查詢陣列，淘汰時也確實相加 `nbytes + resident_bytes()`。但測試把上限設成「一份表 + 1 byte」再裝兩份表，即使移除 `resident_bytes()` 也會淘汰。應把上限設為兩份 wire tables 放得下、加上 query arrays 才超額。另有三個邊界：命中時未更新次序，實際按安裝順序淘汰；舊 selection 強參照可留住已淘汰 index；安裝後 `paths` 仍可改，使預熱的 flags／bbox 過期。`model/vector_paths/index.py:39`、`:47`、`:59`；`model/pdf_model.py:4491`、`:4499`、`:4506`、`:4568`；`test_scripts/test_vector_movable_subset.py:197`；`test_scripts/test_vector_scan_child.py:62`

2. **OCR 逐頁確認寫入與通知。** drain 先移走整批；若 page-key 查詢或通知 hook 拋例外，後續頁會從佇列消失。若文字已插入但 `rebuild_page()` 失敗，呼叫端會收到 `Stale`，快照卻已過期。正常直接寫入又由 model hook 和 coordinator 各通知一次。建議每完成一頁才出列，由單一入口通知並更新 dirty 狀態。`model/pdf_model.py:4252`、`:4271`、`:4430`、`:4445`、`:4461`、`:818`；`controller/ocr_coordinator.py:284`、`:291`、`:295`

3. **補持有者的巢狀呼叫契約。** 五個 lifecycle 方法都已列入 gate，但 `gated()` 會取走 `write_lease`。合法持有者呼叫 `close(write_lease=lease)`，進到 `close_all_sessions()` 仍會被自己的 gate 拒絕；`save_session_as() → save_as()` 同理。另請明訂 vector Undo／Redo 的發布點，目前只有 `record()` 設定 `published`。`model/write_gate.py:115`、`:161`；`model/pdf_model.py:870`、`:884`、`:2403`；`model/edit_commands.py:1468`、`:1503`、`:1537`

**Evidence**　`git diff --check` → exit 0。審查基準為 `feat/true-text-edge-cases`、HEAD `4f608d04`，含未追蹤的 gate 與測例。  
**Not performed**　依要求未執行 pytest、Qt、benchmark 或計時。`plans/b7-progress.md:36` 的 suite 數字為既有紀錄。  
**Fence log**　全程唯讀；`CLIPPED` 放寬未列入本輪判定。  
**Verified**　以空 OCR 佇列、另一個已開啟的分頁、已接受的整窗關閉事件，以及同 token 不同 mask 反查正常路徑，均找到可由現碼走到的反例。

**接線判定：暫緩啟用正式 `vector_delete`。** 下一步適合先做 controller 整合測例，讓 T0／T1 的回呼實際觸發 CLI 切頁及關窗，再注入 after-capture／`record()` 失敗，核對原分頁、文件、history、OCR 佇列與選取範圍。這些條件成立後，再開放刪除動作；第二輪已指出可能選錯 parent 的零長度筆段命中問題，也應在開放前修正或保守拒絕。`plans/b7-review-r2.md:110`、`:116`；`plans/b7-progress.md:23`；`model/vector_paths/index.py:269`、`:332`

## Recurrence
- This round: write entries and lifecycle paths that bypass or outlive the gate (CLI open switching session inside the pump, whole-window close, direct OCR submit on a latched session, direct tool hooks), plus transaction publish boundaries.
- Previous round: the same mechanism: entries missing from the hand-kept inventory (resize_object, lifecycle), commit returning None draining OCR, live reads passing the busy guard.
- Same mechanism: yes (third review in a row finds another entry the gate does not cover).
- Class fix: stop adding entries by name. Outcome check: a controller integration test whose T0/T1 `on_yield` callback fires every queued entry (CLI open of another document, tab switch, window close, undo/redo, OCR delivery, timer-driven index build) and then asserts, after the commit, that document bytes, history, OCR queue, selection and active session equal the expected state; plus commit_delete re-validating (session, handle_generation, content_revision) after every yield. Until that test exists the wiring of vector_delete stays off. Not patched this round by design (rule: two consecutive rounds, same mechanism).
