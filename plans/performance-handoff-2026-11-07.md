# 效能工作交接：2026-11-07

## 目前狀態與接手第一步

- **未完成全階段驗收，不能宣稱全面加速或正常預設交付完成。**
- 現有工作就在目前 checkout；分支 `feat/true-text-edge-cases`，HEAD `e5ed5d6`。大量 tracked 修改與 untracked 新模組尚未 commit。接手先查 `git status --short`，不要重置、覆寫、清理或重新開工。
- 現行主計畫：`plans/app-performance-v2.md`；M2 詳細契約：`plans/watermark-process-route.md`。歷史方案與摘要不能取代目前原碼及證據。
- 實作以 `33a70c4` 為基礎；比較基線 `0663a1c`。本次 lazy-print 對照只是同 build 的 eager/lazy 比較，**不是**整體基線驗收。
- 正常預設仍是 **thread**；retained DisplayList 預設關閉。process 模式已可診斷使用，尚未符合切預設門檻。
- 使用者暫停 whole suite；focused tests 與 supervised App 實測允許。未收到恢復 whole suite 的新指示。
- 最新獨立 reviewer 未交回結果：Codex 額度耗盡。`test_render_process_pool.py` 最新重跑在執行前被自動審核額度錯誤阻擋，**沒有執行、不是測試失敗**。不得繞過審核或假稱通過。
- 沒有仍在執行的 App driver 或 pytest。最新 reviewer 以額度錯誤結束，不要自行重派同一代理。
- 下一步先保存／檢查現有 diff，再完成最新 DPI／pool／句柄修正的獨立審查；之後 M2 fault matrix 與 M6 無 profiler 的 A/A、等工作量開檔量測。M4 production admission 仍需要實作。

## 1. 目標與必要驗收成果

| 面向 | 必須交出的成果 |
|---|---|
| 每個 baseline >=100 ms 的操作 | 每檔、每狀態、每操作各自至少快 20%；不得用平均值掩蓋退步 |
| 原本快的操作 | 不超過預先凍結的 A/A 雜訊界線，且界線最多 5 ms |
| GUI 回應 | p95 <=50 ms，已觀察最大值 <=150 ms |
| 暖跳頁／縮放 | 真正目標可視內容高品質 paint p95 <=250 ms |
| 冷啟動帶檔開啟 | 指令至高品質可視內容 p95 <=1 s、最大 <=2 s，含 child startup |
| 背景完整完成 | HVAC 50 頁 <=15 s；heavy 90 頁 <=20 s，同工作量與品質 |
| 記憶體 | App + 全部 owned children 同時 RSS peak <=baseline +300 MiB；另報 private commit、可用 RAM、paging |
| 正確性 | 浮水印、註解、色彩、DPR、文字外觀一致；編輯／Undo／Redo／存檔後不顯示舊版 |
| 生命週期 | 取消、超時、child crash、快速跳頁、關窗、存檔都不漏 child／reader／lease；fallback 原因可追蹤 |
| 正常啟動交付 | 真正 launcher／雙擊／CLI 帶檔／App 內開檔均驗證；不能只讓測量 driver 過關 |

全量量測依主計畫至少二十次配對 session／一百次操作建立 p95 證據。冷啟動、OS cache 冷暖與新 App process 要分別標示，不能互換。

分開記錄：首次回饋、首次目標內容、可視區高品質完成、操作完成、背景完成。placeholder／低解析／舊像素只算回饋，不算完成。
背景完成須包含既定縮圖數量、尺寸、版本、色彩、註解及 baseline 原有索引／metadata 義務；不得透過略過工作達標。

## 2. 階段 done-map

| 階段 | 已有實作／證據 | 尚欠的交付 |
|---|---|---|
| M0 量測契約 | `scripts/perf_completion.py` 與 completion checks；public-entry driver、外部記憶體 sampler | 凍結全操作 inventory、A/A 界線、等工作量控制；完整配對結果與缺漏樣本處置 |
| M1 取消／生命週期 | 邏輯 supersession、非同步 retirement、前景召回；新 native reader 防護 | 並行 native open／其他 CRT 的繼承競態；save-reader 非同步整合；完整 fault/shutdown matrix |
| M2 全面移出 GUI raster | 連續／單頁、低高解析、縮圖、搜尋及 frozen watermark process 路徑；DPR/editor/reentry 修正 | 更廣 actual-App fault 與品質等價驗證；最新獨立 review；每條 fallback 不在 GUI 偷做重型 raster |
| M3 快取 | retained DisplayList 原型、版本與 watermark 排除規則；focused 39 項歷史通過 | 保持 off；實際 App 命中、首次建置成本、Undo／save 失效、記憶體與收益資格 |
| M4 排程／資源 | App-wide pool、前景 paint gate、公平性；Qt-free ledger、optional client lease adapter | **尚未接妥 production App/helper/buffer/cache admission**；真實 native 配額與低記憶體降級；兩 worker 採用證據 |
| M5 clip／tiles | feasibility 有像素反例 | 正確性未過，暫緩採用；不可因微探針倍率而啟用。可用替代路徑達標並保留拒絕證據 |
| M6 其他操作／開檔 | recent history I/O 隔離、annotation 預篩、lazy printing、optimizer executor lazy import | 開檔仍未達標；搜尋／文字預覽／結構／存檔／列印／OCR 準備操作 inventory 與量測；只在證實瓶頸後設計 operation host |
| M7 正常預設交付 | 尚未接受 | 同版本全驗收、回歸／獨立審查、資源門檻後才能變更正常 default |

**沒有一個 M 階段可因局部 tests 綠燈直接標為整體完成。**

## 3. 本輪改了什麼／誰做的

### Codex 本機實作與驗證

- `controller/pdf_controller.py`、`view/pdf_view.py`：連續搜尋及 single-page process navigation/search/zoom/save。高品質回覆更新像素而不拆掉同頁 editor；導航先完成 editor preparation 再擷取 generation，避免同步 reentry 送出舊工作。
- `view/canvas_view.py`：DPR 事件通知。Controller 降低舊 high 品質紀錄、重新排程、丟棄舊結果；single-page 真正 current high paint 才通知 pool 前景已呈現。
- `model/watermark_raster.py` 及 coordinator/worker/protocol：有界不可變 watermark recipe、版本 currency、dirty snapshot；覆蓋頁不重用不適用的 DisplayList。
- `utils/native_handle_inheritance.py`：在 metadata／render／print 三個 owned QProcess 的實際 start 前，清除觀察到的 CRT disk handle 繼承旗標。掃描 lowio 上限 8192，不誤用 stdio 512 上限；不動 pipes/std handles。
- 此句柄措施**不是原子性全程序保證**：掃描後並行 open、其他 runtime 與 handle reuse 仍需驗證；不能稱所有 save/replace 錯誤已修完。
- `model/pdf_optimizer.py`：平行分支才 import ProcessPoolExecutor，serial 分支不預付 import。
- 實際 App driver、red/green tests、證據判讀、套用 proposal、文件均由 Codex 執行。

### Claude API 的實際責任

- Sonnet 收到已逐份核准的列印初始化片段，提出 lazy printing patch；Codex 檢查、調整並套用 `src/printing/__init__.py`、`controller/print_coordinator.py` 與 activation 路徑。
- 第一次 8192 token 回覆耗在 thinking 且 `max_tokens`，沒有完整 patch；第二次 16384 完成，output 12176（thinking 7856）。失敗／截斷保留證據，不計實作完成。
- Generic Opus native-handle advisory 回覆 `refusal`、沒有可用正文；不得把它計為已審查。local deep-reasoner 的設計分析曾完成，最新 fixed-diff review 未完成。
- API 工具只回傳文字，**不會操作 repo、執行 tests、看實際 App 或自行驗收**。其他過往 API 呼叫以個別 JSON 和 prompt 為準，不能推定為本機實作者。

## 4. 最新可重現證據

所有下列 run artifacts 位於 `_evidence_pilot/performance-v2/`，不加入 commit。機器路徑／個資只留本機 artifact。

| 證據 | 結果及範圍 |
|---|---|
| `single-route-final.txt` | 最新 17 passed；之前 DPR／pool 3 failed /14 passed ->17 passed |
| `canvas-final.txt` | 2 passed |
| `page-process-final.txt` | 18 passed |
| `test_render_process_pool.py` 最新回歸 | 未執行：automatic approval review 額度錯誤；不要把舊 16 passed 當最新結果 |
| `single-editor.json`、兩張 `single-editor-*.png` | public `main.run`，125%、真實 IME-retaining Ctrl+S、Apply／Undo／Redo／save、重新讀 saved PDF text；exit0、fallback0、child reaped。特定 fixture 正確，不是全 corpus fidelity |
| `lazy-print.json`、`lazy-print-dialog.png` | 正常 thread 啟動後真實 Ctrl+P，首次 dispatcher/dialog 約261 ms；取消零 snapshot／零 submission。畫面已檢視；未驗證實體列印或冷開機 |
| native reader focused | 9 passed；metadata/render/print 真 child、兩 PDFs、fd1024、pipe 保留、拒絕啟動 cleanup |
| 舊 print-cancel flow 回歸 | 4 passed；recent probe6、print runner7、render client45、live child2 歷史本輪通過 |
| 其他本輪 focused | search11；save/composition subset48；print cold5、extraction4、signed save40；optimizer cold1、workflow47/skip4、immutable19 |
| 全樹 ruff | 最新 `python -m ruff check .` exit0 |
| 型別／分層 | 本輪 earlier mypy model/utils87檔通過、import contracts4 kept；最新僅 docs delta 不影響 |

### 開檔量測必須保留的反證

舊 profiler ABBA：Office first-high control5747/6194 ms，lazy4456/6916 ms，均值只改善4.77%；background 無非退步證據。

最新 **無 profiler** 同 build ABBA（CLI public entry，process1 worker、相同26影像、相同IPC17951866 bytes）：

| artifact stem | first high ms | 全縮圖 idle ms | combined peak RSS MiB | missing-PID 樣本數 |
|---|---:|---:|---:|---:|
| `m6-light-control-a` |1548.1|1787.7|383.6|0|
| `m6-light-lazy-b` |1339.5|1574.1|401.5|0|
| `m6-light-lazy-c` |1447.7|1676.1|401.8|0|
| `m6-light-control-d` |2578.4|2854.1|383.3|1|

四次 exit0、fallback0。候選 first-high1339/1448 仍超過 p95 1s 目標；GUI max728/746 ms 仍超過150 ms。control 波動很大且一個 PID 漏取樣，不能據均值宣布成功，也不是 reboot cold/A/A 校準結果。
`first-show-attribution.json` 把 Qt/PDFView import 排除後觀察 native show 約753 ms（thread CPU703 ms），不能冒充完整啟動時間；native Qt show attribution 仍開放。
舊 HVAC watermark diagnostic：跳頁172.48 ms，zoom267.44 ms（未過250）；single search entry6.13s、revisit20.89ms；revisit 是 cache-hit，不是首次搜尋證據。

## 5. 接手順序與逐步完成條件

1. **固定現況**：讀 git status/diff、上述兩份 plans 與 artifacts；不要重跑已完成 lane，不要把未 commit 工作丟掉。使用者目前要求交接，非新增效能實作或 commit。
2. **獨立 review（已完成，2026-11-07 後續）**：Opus 5.5 子代理（唯讀，直接讀 repo）審 `786be68` 的 M2 DPR/pool/single-editor 與三處 native handle start，裁定 **fix-first**（僅涵蓋該 delta，不是整體效能驗收）。我逐項核對原碼後：
   - 發現1（med，已修）：handle guard 掃描中 fd 被他執行緒關閉／替換會丟例外，`RenderProcessClient.start()` 因而永久 `_disabled`。紅燈3項→`_clear_descriptor` 跳過已消失 fd、換手 fd 重讀最多3次、仍不穩定才 fail-closed；`test_native_handle_inheritance` 13 passed。
   - 發現2（med，已修）：pool 全部停用後縮圖仍走 process 往返並在 GUI 執行緒繪製。紅燈1項→新增 `RenderProcessPool.unavailable`，coordinator 改走 file-worker／live 路徑；`test_thumbnail_process` 14、`test_render_process_pool` 17 passed。
   - 發現3（low-med，**待 M2 fault matrix**）：單頁模式導航後該頁 job 失敗：`RenderTransportLost` 有隔離提示（既有設計），`RenderTimedOut`／一般失敗只 log，畫面留白且搜尋高亮被丟。需先寫失敗重現再決定是否補提示／重試。
   - 發現4（low，待處理）：`ThumbnailCoordinator.__init__` 連接 `job_done/image_revoked`（建構期而非 `activate()`），release 後不中斷連線。
   - 發現5、6（low，speculative）：Windows 粗時鐘使 150ms recall 最多延至約250ms；`painted` 在 paintEvent 內同步觸發 pool `_pump`→child 啟動。需量測再定。
   - Opus 未驗證：DevicePixelRatioChange 在 PySide6 螢幕切換的實際送達、editor mask 於就地換像素後、非同步文字 commit 後是否必重繪。這些列入 fault matrix。
   - 修正後 focused：native_handle 13、thumbnail_process 14、pool 17、render_process_client 45、thumbnail_coordinator 22、live worker 2、page_render_process 18、single_page_route 17、canvas 2 全過；全樹 ruff、mypy model/utils 87 檔乾淨。尚未做修正後的第二次 Opus 審查。
3. **M2 fault matrix（2026-11-07 完成，待下一輪 M2 大改動後再送 Opus 審）**：發現3已修（紅燈3項→`_notify_single_page_render_failure`；timeout／一般失敗在單頁模式出一次提示並清 target，連續模式維持靜默，既有 quarantine 測試未改）。發現4經查**不是缺陷**：coordinator 為 QObject、連到 bound slot，銷毀時 Qt 自動斷線。新增 `test_render_fault_matrix_live.py`（真 pool＋真 child＋浮水印；單頁與連續模式在「當前 job 執行中」殺 child：提示、只隔離該頁、他頁照常；關閉中 pending render 不上畫面且 credit 歸還；連跑5次穩定）與單頁 commit 失效後同 item 就地換像素測試（護欄，非紅燈）。真 App：`verify_single_editor.py` 真編輯／Undo／Redo／Ctrl+S exit 0；新 `verify_fault_matrix.py`（process 模式、浮水印、單頁、殺 child）exit 0，提示出現、第3頁照常渲染、結束時 child 被回收（截圖 `_evidence_pilot/performance-v2/fault-matrix.png`）。focused 全綠：single_route 22、page_render_process 18、fault_live 3、pool 17、client 45、thumb_coord 22、thumb_process 14、canvas 2；全樹 ruff、mypy 乾淨。**仍未做**：實際跨螢幕 DPR 事件送達（僅注入測試）、timeout 的 live child（用 fake 覆蓋）、save 失敗在單頁的 live 驗證。原項目：帶浮水印及 dirty PDF，continuous/single/search/zoom/navigation、save fail/success、close/crash/timeout；證明 frozen revision、過期丟棄、fallback、credit 回收、無 editor/IME 遺失。實際跨螢幕 DPR 尚未做，目前為事件注入測試。
4. **M6 A/A 與開檔 attribution**：同 entry/settings/backend/file，無 profiler 做 A/A，再 ABBA；把 setup/import/native show/Model open/snapshot/raster/paint 拆開。保留平常 recent history，不用空設定掩蓋問題。
5. **M4 production 資源整合**：App、全部 helper、worker、retiring child、snapshot、IPC、image、cache 同時記帳；容量未知不得稱 admission 通過。依真實 RAM/RSS 及 +300MiB 門檻比較1/2worker；3/4僅診斷，不假定線性收益。
6. **M3/M6 剩餘操作**：量測 cache 與索引/編輯/預覽/結構/存檔/列印/OCR；瓶頸有證據再改設計，保留 invalidation/quality/undo 契約。
7. **M7**：取得全矩陣、記憶體、品質、fault 與獨立審查證據後，按權限恢復必要 release gates，再接正常 default/launcher；目前 full suite 暫停須明列限制，不能略過後稱正式驗收。

## 6. Claude token 與模型分工交接

- **已更新（接手後）**：`scripts/claude_api_tool.py` 上限由16384改為模型同步輸出上限 **131072**，預設仍4096；超過16384改走 streaming（SSE 重組成同形 JSON，提早結束時保留部分文字並標 `stream_incomplete`），避免單次非串流請求超過90秒讀取逾時而計費無結果。`--call-limit-usd` 預設$2 不變：Opus 128K 約$2.62，需使用者明確加大才能呼叫。紅燈13項→`test_claude_api_tool.py` 23 passed、ruff 乾淨。**尚未對真 API 實測 streaming**（未花任何 API 費用）；首次實際大上限呼叫須先經使用者核准，並檢查 `stop_reason`/usage。
- 先前狀態（供對照）：舊工具硬上限16384、預設4096；`docs/codex/CLAUDE_API.md` 寫8192起始。
- 官方 Sonnet5.5：輸出128K、標準input $2/MTok/output $10/MTok；thinking 占 max_tokens 且以 output 計費。來源：<https://platform.claude.com/docs/en/models/sonnet-5-5/overview>、<https://platform.claude.com/docs/en/build-with-claude/thinking>，2026-11-07查核。
- 輸出上限政策（已寫入 `docs/codex/CLAUDE_API.md`）：小範圍 review8K–16K；implementation32K；跨模組設計／長 patch64K；必要時最高128K。boundary/budget/streaming 測試已補，credentials/ledger 契約不變。
- 32,768 output 的 Sonnet標準費用上限約$0.32768，65,536約$0.65536，另加輸入；比現有$0.20單次核准更高，不能靜默沿用舊核准。max_tokens是上限，實際依usage；本機ledger保守預留且不退款。
- 持續用 `_evidence_pilot/claude-api/budget.json` 一份帳本（總額$200），不要重建帳本。不印出或複製 key；API並非一定可無條件接收任何新私有原碼，遵守逐份 payload 核准與審核結果。
- 建議 Terra 做主對話的證據整理、明確方案套用與測試協調；Luna 僅做規格固定、低風險機械工作；Claude Opus做架構／競態反證，Sonnet做有界實作proposal，Fable留衝突或反覆未達標的架構問題。
- **不能保證 Claude 指揮 + Terra/Luna 等同高階主模型品質。** API 看不到未提供的現場；主模型仍須理解diff、驗證錯誤與識別測量漏洞。要以相同patch/workload的缺陷數、回歸、驗收達標、總費用及耗時比較；不要把模型稱號當證據。
- 使用者後續建議的分工（未啟用，僅記錄）：Terra 協調與執行；Sonnet 實作提案；Opus 架構與獨立審查；Haiku 大量、可驗證、低風險的平行任務；重大瓶頸／架構爭議交 Fable；Luna 只做規格固定的機械修改，不承擔整個主對話。工具已計價 Opus 5.5 4/20、Sonnet 5.5 2/10、Fable 5.1 10/50、Haiku 5.5 0.10/0.50（prompt >100K token 為 0.50/2.50，依 count 分級）；Fable 128K 約$6.6、Opus 約$2.6，須明確加大 `--call-limit-usd`。紅燈6項→29 passed。**串流真 API 驗證已執行**：Haiku 5.5、`--max-tokens 20000`（走串流）、約$0.01 保留，exit0、`stop_reason=end_turn`、usage 由 message_start/message_delta 合併正確（input60/output21）、content 與非串流同形。產物 `_evidence_pilot/claude-api/stream-verify-haiku.json`（未 commit）。這只證明串流格式與計價；**長輸出（數分鐘、數萬 token）的耐久性尚未驗證**，留給第一次真實 32K 任務，並檢查 `stop_reason` 非 `stream_incomplete`。驗證方式同上：同工作量比較缺陷數、回歸、驗收通過率。
- **使用者決定（2026-11-07 後續）**：(1) Terra/Luna 在 OpenRouter 無額度（`Insufficient credits`）、Codex 額度耗盡，改用 Anthropic 模型：Sonnet 當 Terra、Haiku 當 Luna，主對話 Sonnet，Opus 做架構／獨立審查。(2) WIP commit 已建（`786be68`，不代表達成任何結果；`.agents/skills` 的 9 筆刪除與 `_evidence_pilot` 6 個舊腳本換行變動未納入，仍在工作目錄）。(3) **whole suite**：等全部改善做完後一次跑，或在 22:00–08:00 睡眠時段跑（耗時耗記憶體）；之前不跑。(4) 必達目標以 `plans/app-performance-v2.md §1` 與本文件 §1 為準；若無法達成，交 Opus、Fable 再各追一次，仍未達標則列出證據、不宣稱完成。
- 不更改目前 session model 或 `.codex/agents` pin；切換是另一步。現有角色串行、只跑一個pytest；API proposal不取代獨立驗收。

## 7. 操作與不做事項

```powershell
.venv\Scripts\python.exe -m pytest test_scripts/test_single_page_process_route.py -q --tb=short
.venv\Scripts\python.exe -m pytest test_scripts/test_canvas_presented.py -q --tb=short
.venv\Scripts\python.exe -m pytest test_scripts/test_page_render_process.py -q --tb=short
# 下項是未完成回歸；前項結束才開始
.venv\Scripts\python.exe -m pytest test_scripts/test_render_process_pool.py -q --tb=short
.venv\Scripts\python.exe scripts/verify_supervise.py --stall 120 --ceiling 180 -- _evidence_pilot/performance-v2/verify_single_editor.py
.venv\Scripts\python.exe scripts/verify_supervise.py --stall 120 --ceiling 180 -- _evidence_pilot/performance-v2/measure_entry.py --file test_files/office-report-23p.pdf --mode process --external-memory --output <fresh-artifact.json>
.venv\Scripts\python.exe -m ruff check .
```

測試stdout/stderr存artifact並讀exit，不因尾端Get-Content成功而丟掉pytest exit。sandbox tempfile建立錯誤屬環境，不新增shim/sitecustomize、不改TEMP；正常環境重跑需走正式審核。最新審核被額度限制阻擋，未獲執行。
所有 gate 保持foreground至exit。禁止process kills、ruff format、未請求git寫入、整批pytest。未做實體列印／冷開機，未發現可宣稱所有操作已加速的證據。
Fence：既有Model overlay-copy註解mutation問題未納入本輪修法；其餘to_Update功能、歷史holdout尚未因本效能工作自動完成。不要混入未相關功能或commit。
