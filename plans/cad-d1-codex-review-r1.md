# CAD D1 Codex review R1 — 2026-11-19

| id | severity | file:line at `71fa1ba9` | claim | how shown |
| --- | --- | --- | --- | --- |
| R1 | blocks | `model/pdf_model.py:1412` (producer gap: `:4287`) | `content_revision` 仍漏掉已寫入、但在成功記帳之前失敗的操作；OCR 後索引重建失敗時，已過期的「沒有表格」答案仍會被接受。 | 在乾淨 commit 快照執行真實 PyMuPDF OCR 寫入，只令索引重建拋錯；重算偵測有表格、快取仍為空、舊答案可再次存入。 |
| R2 | should fix | `test_scripts/test_frame_key_revision.py:41` | class check 的 digest 未涵蓋 Form XObject 等間接資源；表格已消失仍可得到同一 digest，造成驗收假陰性。 | 在真實 Form XObject 表格上做負控制，清空內層 stream；重算表格從一個變零個，digest 不變。 |

## Result and scope

審查範圍只含 `ebb86561aa5119a560247d482b00783ed021c408` 與 `71fa1ba9554d5e3156e59498396c03b849091a4f`。所有下列程式碼行號均指後者，並非目前含 A5 變更的工作樹。

Handle generation、跨分頁保留及 stale-drop 的主要修正成立；revision 修正確實補上已列的 undo/redo 問題，但 **D1 的「文件已變更就不再接受舊答案」驗收尚未封閉**。R1 是新 revision 消費端未涵蓋既有寫入路徑的整合缺口，不宣稱 OCR 的錯誤處理是本次才新增。R2 是這次新增驗收測試的缺口。

只新增此報告。沒有修改產品程式、既有測試、A5、TODOS 或 handoff，也沒有 commit。兩個 reader 子代理依序調查 handle/stale 路徑與其他 mutation 路徑；主代理在 commit 快照覆核並執行重現。

## R1 — 失敗前已寫入的操作仍可保留舊 revision

`content_revision` 只讀取 `edit_revision` 與 `command_manager.revision` (`model/pdf_model.py:1412`)。這能涵蓋命令管理器的 `finally`，卻不能涵蓋外部先寫入、稍後才 `record()` 或修改 `edit_count` 的失敗出口。

已執行的主要反例：

1. 建立 300 × 300 頁面，上有 3 × 3 空格線。真實 `find_table_rects` 回傳 `[]`，以當前 key 存入快取。
2. 呼叫 `apply_ocr_spans(1, ...)`，在第一格插入 `cell`。只將 `block_manager.rebuild_page` 替換成拋出 `RuntimeError` 的失敗注入；沒有 mock PyMuPDF document 或文字寫入。
3. 字已寫入 (`model/pdf_model.py:4267`)，但 `:4287` 重建索引拋錯，跳過 `:4290` 的 `edit_count += 1`。
4. 原始 `_digest` 已改變；重新從 scratch page 偵測得到 `(50, 50, 200, 200)`，`cached_table_rects` 卻仍回傳 `[]`，且 `store_table_rects(model, old_key, [])` 回傳 `True`。

實測輸出：

```text
fresh_tables=[(50.0, 50.0, 200.0, 200.0)]; cached_tables=[]; old_answer_accepted=True
FAILED test_failed_ocr_cannot_reuse_pre_ocr_tables
assert table_objects.frame_key(model, 1) != old_key
```

這是可抵達的 production 呼叫鏈：`controller/ocr_coordinator.py:266` → `apply_ocr_spans`；`:280` 捕捉並記錄錯誤後，繼續保留該文件，不會補 tick 或 rollback。因此影響不只是一個內部屬性：有表格的頁面仍被當作已分析完成且沒有表格。故障前送出的答案也能通過相同 key 檢查。故障注入證明的是失敗出口的正確性，並未聲稱一般 OCR 必然觸發索引錯誤；既有 OCR 測試 20 項全過。

同類的第二個已執行反例：`PDFController.add_highlight` 先呼叫真實 annotation tool，再取得 after snapshot (`controller/pdf_controller.py:3247`)，最後才於 `:3260` record。令第二次 snapshot 拋出 `MemoryError`，annotation 已存在、digest 已變、key 卻不變。這個反例以最小 controller 接收者呼叫真實方法；render invalidation 被替換為 no-op。實際 `_invalidate_active_render_state` (`:1694`) 只動 render revision，沒有更新此處的 content revision，所以不會推翻結果。**不宣稱 annotation 本身會改變 table detection**：scratch page 明確排除了 annotations；此例補證 H22 文件修訂識別與 `record()` 前的同類缺口。

修正應把 revision 與實際寫入邊界綁定，覆蓋成功、部分失敗以及外部先做後 record 的操作，不能只在這兩個 catch 補案例。至少要確保任何留在 live document 的變更，在恢復事件處理或離開操作前已使舊 key 失效；若有可重入寫入，亦須檢查中途使用快取的時機。

## R2 — class oracle 沒有觀察到間接的頁面內容

`_digest` 只 hash `page.read_contents()`、annotation 的 type/rect/content 及 boxes/rotation。`read_contents()` 是頁面的外層 `/Contents`，不會遞迴 hash `/Resources/XObject` 的 stream。CAD 內容常放在 Form XObject；目前宣稱的「What table detection reads」並不完整。

已執行的負控制：用 `show_pdf_page` 將帶有 `cell` 的格線頁置入另一頁，保留它回傳的 Form xref。初次偵測有表格。直接將該 Form stream 更新為 `b"q Q\n"`，外層 `/Contents` 與 boxes 不變。

```text
tables_before=[(50.0, 50.0, 200.0, 200.0)]; tables_after=[]; digest_changed=False
FAILED test_digest_observes_form_xobject_changes
assert _digest(model) != before
```

若把這個操作加入 `_OPS`，`test_a_changed_page_never_keeps_its_frame_key` 的條件會因 digest 相等而跳過，測試錯誤通過。這是測試 oracle 的負控制，**不是另稱 production 存在一條直接清空 Form 且漏 tick 的路徑**。

應以穩定的頁面依賴內容指紋涵蓋實際被讀取的間接資源，或用獨立的 fresh analysis 結果作為相關負控制；避免以會自動變動 `/ID` 的整份存檔 bytes 充當 oracle。保留「只改 Form stream 而不改外層 Contents」的負控制，證明 oracle 真能辨認這類變更。

## Answers to the brief

### 1. Handle replacement

在已查的 production handle 指派／建構路徑，未找到替換 live handle 卻沿用 generation 的案例。setter 的兩分支都在 handle 不同時取新 generation (`model/pdf_model.py:893`)；兩個 `DocumentSession(...)` 建構點 (`:1958`, `:2037`) 取 default factory 的新值。跨 model transfer 重新開啟 snapshot 後建立 session，未搬移既有 generation。直接 `_legacy_doc = None` 清除是 `close()`，不是裝入另一個 live handle。

### 2. Mutation coverage and whether `_OPS` would catch it

| 路徑 | 已查結果 | 加入現有 `_OPS` 的判別能力 |
| --- | --- | --- |
| rotation | `rotate_pages` 改 rotation；controller 完成後亦 record (`controller/pdf_controller.py:3183`)。 | 會；現有清單已涵蓋。 |
| OCR | 成功時 `edit_count` tick；重建索引失敗可在 tick 前離開（R1）。 | 會抓到 R1，須讓操作包裝器接住預期錯誤以繼續比較。 |
| annotation/highlight | 成功 controller route 會 record；after-snapshot 失敗時不會（R1）。 | 新增 annotation 的 type/rect/content 改變會被抓到；僅 appearance/color 的變更未被此 digest 完整涵蓋。 |
| semantic redaction | 檢查的文字成功路徑於 `model/pdf_text_edit.py:5033`, `:5173` tick；object bookkeeping 於 `model/pdf_object_ops.py:240` tick，atomic deletion 有失敗復原。 | 直接 Contents 改變會；間接 Form 改變受 R2 限制。未宣稱遍歷所有例外分支。 |
| `apply_pending_redactions` maintenance | 名稱雖含 redaction，實際是 `clean_contents()` (`model/pdf_model.py:5341`)；本函式不 tick。save 在 `:6585` 呼叫它，成功才於 `:6718` 重設 edit_count。若 save 中途失敗，可能保留重寫的 stream 與原 key。 | 清理改變外層 stream 時會抓到；本項為讀碼發現，未另執行 failed-save 重現，未證明表格幾何變更，不另列表格快取缺陷。 |
| optimize | `model/pdf_optimizer.py:1030` 起的 source capture / working copy 路徑使用來源快照或 clone，未找到這條 export 流程改 live page。 | 無 live 改動時不應失敗。 |
| watermark | `model/tools/watermark_tool.py:195` 的 overlay 與 `:219` 起的 save clone 分工；bake 在 clone (`:242`)。 | 無 live 頁面 bytes 改動時不應失敗。 |
| form fill | 在 model/controller 的 widget/field-value/update/form 搜尋，未找到 production 表單填寫 writer。 | 不能以不存在的 route 宣稱涵蓋；若只變 widget/AP，當前 digest 不足。 |
| page reorder | `PDFModel.move_page` (`:2660`) 本身不 tick；正常 controller route 於 `controller/pdf_controller.py:3174` record。 | 直接只呼叫 model 方法，且兩頁同框而內容不同時，會暴露無 tick；完成 controller route 則有 tick。不另當作完成後仍 stale 的實測缺陷。 |
| controller 直接操作 doc | 查得的 indexed doc 存取為 rect/rotation 讀取；已找到的寫入由 model/tool 路徑完成。 | 不把「未找到」當作所有未來 writer 的保證。 |

### 3. Retirement

`close_session` 先移除 session 再 retirement (`model/pdf_model.py:830`)，`live_handle_generations()` 包含所有剩餘 sessions 與 legacy handle (`:924`)。未找到誤刪其他 live tab 結果的路徑；跨 tab 測試通過。

`close()` 在 `close_all_sessions()` 後直接清掉 `_legacy_doc` (`:2403`) 而未再 retirement；若有 legacy entries，model 仍被持有時可暫留，之後 retirement 或 weak-key model collection 才移除。這是 brief 已指明的 memory-only 限制，不新增 finding。

### 4. Stale drop

coordinator 先從 `_jobs` pop，再進 `_is_stale` (`controller/object_probe_coordinator.py:100`, `:129`)；return 不會保留該 job 阻擋下一次同 key request。已查的 controller/view 使用非阻塞 signal callback，未找到必須等 `tables_ready` / `probe_failed` 才能解除的同步 wait。pending click 可等待其他取消／更新動作；不把 brief 排除的 status bar 問題重新報告。

### 5. Command ordering

`execute` / 非空 `undo` / 非空 `redo` 的 `finally` 位於 command body 後 (`model/edit_commands.py:1408`, `:1475`, `:1508`)。body 中取得的 revision，在函式離開後會因最後的 fresh tick 失效；拒絕與拋錯也成立。空 stack 沒有 tick，但亦無 command body 執行。未找到現有 command 在寫入後透過 `processEvents` 消費 stale answer 的實證，不另報可重入性缺陷。

`record()` 在入口取 tick (`:1448`) 只封閉呼叫之後的狀態；它不能補救「操作已寫入卻在抵達 record 前失敗」的窗口。R1 的 annotation 反例已實測此差別。正常同步完成 record 的操作不能僅因存在這個窗口就判成 bug。

### 6. Parent red-light replay

父版本從 `git archive` 建立在暫存目錄；沒有 checkout/reset 或改動使用者工作樹。把受測的新測試放入父版本；第二輪只將三個 production Python 檔更新至 `ebb86561`，等同 `71fa1ba9` 的 runtime parent。所有 pytest 逐檔、串行使用本 repo 的 `.venv` interpreter。

| 檢查 | runtime | 結果與原因 |
| --- | --- | --- |
| `test_table_probe_non_mutation.py` 最後六項 | `504e6c0d` = `ebb86561^` | exit 1，6 failed / 10 deselected。兩項 forced collision 顯示舊值洩漏／key 相等；跨 tab 保留失敗；三項因 parent 無 `handle_generation` 而 `AttributeError`，這三項本身不是行為層的 red proof。 |
| `test_frame_key_revision.py` | `ebb86561` = `71fa1ba9^` | exit 1，5 failed / 1 passed。undo、redo、相同 edit_count 寫回、換 command manager、操作序列均保留舊 key；digest 穩定性控制原本就應通過。 |

父版本失敗尾段摘錄：

```text
FAILED test_frame_identity_survives_forced_id_reuse
assert [Rect(1.0, 2.0, 3.0, 4.0)] is None
FAILED test_snapshot_replacement_drops_an_answer_for_the_old_handle
assert (42, 1, 0, 3, 0, ...) != (42, 1, 0, 3, 0, ...)
FAILED test_switching_tabs_keeps_each_tabs_results
assert None == [Rect(1.0, 2.0, 3.0, 4.0)]
6 failed, 10 deselected in 3.81s

FAILED test_undo_of_a_page_snapshot_command_changes_the_frame_key
FAILED test_redo_changes_the_frame_key
FAILED test_any_write_of_edit_count_is_a_new_revision
FAILED test_a_replaced_command_manager_is_a_new_revision
FAILED test_a_changed_page_never_keeps_its_frame_key
5 failed, 1 passed in 2.07s
```

## Recurrence

R1 是 brief 已命名的「revision misses a change」再次出現，不是新一類 identity reuse，也不是 restored epoch。R2 解釋為何僅擴充操作名稱清單仍無法封閉同類缺陷。

單一 outcome acceptance 應為：**任何操作離開後，包括拒絕、部分失敗與 undo/redo/save，只要相關頁面的實際分析輸入已變，舊 frame key 就不得繼續被視為 current、讀出快取或接受延遲答案。** 操作若完整 rollback，則確認還原內容；成功／失敗路徑使用同一 outcome 檢查。以涵蓋頁面依賴資源的獨立指紋驗證，並以 Form-only 負控制證明 oracle 可觀測變更。不要再用更多局部原因清單代替此 outcome。

這不重報 D12 已排定的跨文件 stale-delete 測試或狀態列問題，也不延伸到 A5 實作。

## Evidence

下列 target 測試皆在 `71fa1ba9` 暫存快照內，以 repo 的 `.venv/Scripts/python.exe` 執行；命令共用前綴省略絕對機器路徑。

| command | exit / result |
| --- | --- |
| `-m pytest test_scripts/test_frame_key_revision.py -q --tb=short` | 0 / 6 passed |
| `-m pytest test_scripts/test_table_probe_non_mutation.py -q --tb=short` | 0 / 16 passed |
| `-m pytest test_scripts/test_object_probe.py -q --tb=short` | 0 / 56 passed |
| `-m pytest test_scripts/test_ocr_model_insert.py -q --tb=short` | 0 / 20 passed（含正常 edit_count、搜尋與 rendering 控制） |
| `-m pytest test_scripts/test_exact_object_text.py -q --tb=short` | 0 / 187 passed（含本次帶入的 CropBox exact-key guard） |
| `-m pytest test_scripts/test_d1_review_probes.py -q -s --tb=short` | 1 / 3 failed，均為上列預期的 outcome 斷言；非匯入錯誤或 fixture 失敗 |
| `-m ruff check .` | 0 / All checks passed（target 快照，包含診斷檔） |

原始暫存 artifacts：`$env:TEMP/cad_d1_review_9ae8cddc/`（target 快照與 `test_scripts/test_d1_review_probes.py`）；`$env:TEMP/cad_d1_parent_rsnn4n0q/`（父版本快照，最後停在 `ebb86561` runtime）。測試日誌為 `$env:TEMP/cad_d1_{revision_target,tables_target,probe_target,ocr_target,exact_target,review_probes,revision_parent,tables_parent,ruff_target}.txt`。暫存檔未加入 repo。

## Not performed

- 全套測試、mypy、真實桌面 save/reopen UI 驗證：本輪為限定兩個 commits 的唯讀審查；未改產品程式，也不宣稱完整 Done gate 或視覺驗收。
- 未重新逐一驗證所有既有 producer 的每個例外分支；表格明列讀碼、實測與未找到的範圍。
- `test_object_probe.py` 新增 stale cases 在 target 執行，但未另做其 parent red replay；brief 特別指定的 revision 檔與最後六個 handle cases 已重跑父版本。
- 環境故障：對暫存診斷檔呼叫 `apply_patch`，操作為 `Update File: $env:TEMP/cad_d1_review_9ae8cddc/test_scripts/test_d1_review_probes.py`，要補兩個控制測試時，回傳 `apply_patch verification failed: Failed to read file to update ...: 存取被拒。 (os error 5)`。此 patch 未套用，未繞過權限、未改環境；既有三個重現及後續獨立的正常 OCR 測試不受影響。

## Fence log

- 保留原本未提交的 A5 與其他工作樹變更；本輪 repo 產物只有此報告。
- 不處理 brief 排除的 D12 項目、retired child cancellation、既知 legacy memory-only 保留。
- 未 push、commit 或改索引；暫存診斷不是產品修正。

## Verified

試圖推翻「OCR 失敗仍會保留 stale 表格」：使用真實 scratch 偵測比對，確認新內容有表格而快取仍為空，且舊答案仍可存入；正常 OCR 測試 20 項通過，故結論限定於失敗記帳窗口。

試圖推翻「digest 漏掉影響分析的資料」：只改 Form stream，實際 table detection 從一個變零個，外層 digest 卻相同；故不是僅關於無關 PDF metadata 的理論差異。

試圖推翻「annotation 的缺口會被 render invalidation 補掉」：閱讀真實 invalidator，確認它更新的是 controller render revision，未更新 model content revision。
