# True-text UI part 5：邊界案例收尾、存檔守衛、視覺驗收、文件

子計畫，隸屬 `plans/Integrate_proven_PDF_editing_methods_into_the_official_editor.md`（以下稱「母計畫」）。
各階段完成後仍照慣例在母計畫 §6 追加日誌；本檔記錄 part 5 的範圍、順序、分工、決策與死路。
分支 `feat/true-text-edge-cases`，起點 `1f51010`。

## 1. 目標與完成標準

目標：`_evidence_pilot` 的 14 個案例在出廠預設下，從正常 UI 的**每一條**進入與離開路徑都走得通——
字型不跳、位置不跑、非目標內容零差異；拒絕時一律 fail-closed，輸入不無聲遺失。

完成標準（全部同時成立才算 part 5 完成）：

1. 四項擁有者決定（2026-10-05）各有先紅後綠的測試：IME 組字、F5 全螢幕、Ctrl+S、`engine=legacy` 跨頁同意。
2. 阻擋缺陷 1（`pending_page_maintenance` 死路）解除：新增文字框或同意重建後，同頁真文字編輯可 COMMITTED；復原該改寫也可。
3. 步驟 13：受保護頁的存檔守衛、`save` 與 `save_as` 兩條 UI 測試、完整存檔重編 xref 後的 undo。
4. 小缺陷 3、4、5、6、7 修掉（文案、重複 toast、內部代碼外露、`Signal(int)` 截斷）。
5. 步驟 15：14 案例 6 倍裁切與 pilot 輸出比對、Poppler 第二渲染器、使用者實機 IME 驗收。
6. 步驟 16：ARCHITECTURE／FEATURES／架構.txt／PITFALLS（35 條候選）＋索引重生／TODOS／codegraph 重索引。
7. 每階段：`ruff check .` 乾淨、mypy `model/ utils/` 無錯、lint-imports 4 kept、umbrella 出廠預設全過（19 個測試函式＝原 15＋新增文字框後再編輯 4；階段格數 14×8 加 14×6 的新增文字框階段；原寫的「112/112」已過時）、
   無測試退步、紅燈紀錄在母計畫 §6；最後一次完整套件。

使用者規則（不變）：只在副本上測；實驗路徑的 `save_reopen_pass` 不算 UI 成功；`accepted_for_code`／`ui_pass`
未過完整關卡不可翻 1；向量 PDF 不算真文字成功；不可自創 case_id；步驟 16 之前不改 `docs/PITFALLS.md`、
`docs/ARCHITECTURE.md`、`TODOS.md`。

## 2. 範圍外（任何 agent 不得順手做）

- 無損跨頁移動（擁有者：要做，但不屬 part 5）。
- 延遲項：p6 冷點擊 190–217 ms、Apply 整體 2–2.6 s、縮圖 GUI 執行緒重繪、開檔後首次預覽 15–16 s。
- 缺陷 8（預覽在飛時關視窗卡 0.9 s）、缺陷 9（關分頁另存 vs 關視窗存回原檔）。
- 1941 批次第二輪。

## 3. 擁有者待確認（Stage 0 報告後、實作前一次問完）

| # | 問題 | 預設讀法（若擁有者不另說） |
|---|---|---|
| Q1 | Ctrl+S「以現狀提交，跳出提示，照常跳出存檔視窗」：`_save`（`view/pdf_view.py:5573`）在有路徑時本來就不跳視窗。 | 有 token → 先 commit 再存；無 token／被拒 → 文件照現狀存、編輯框與輸入保留、提示文案依實際狀態；`_save` 不加視窗，`_save_as` 照常跳。 |
| Q2 | legacy 豁免只有 `controller/pdf_controller.py:3015` 一處（已 grep）。 | 拿掉該豁免即可，不另擴範圍。 |
| Q3 | 缺陷 1 的解除方式（Stage 0 兩份獨立分析後提案）。 | 見 §5 Stage B；高風險，須擁有者點頭。 |
| Q4 | F5 帶有效 token 時：比照縮放是「先 commit 再進全螢幕」還是「擋下」。 | 以縮放實測行為為準（Stage A 先量，不假設）。 |

## 4. 順序與分工

模型分工：Opus 規劃、設計、審查；Sonnet 寫紅燈與實作；Haiku 只做已完全指定的機械工作；Codex（gpt-6-astra medium）當獨立同儕審查。
子代理一次派一個，不平行。

| 階段 | 內容 | 執行者 | 產出 |
|---|---|---|---|
| 0 | 設計分析（唯讀）：缺陷 1 解法、IME 邏輯／顯示拆分、F5 與縮放實際差異、邊界案例普查 | deep-reasoner（Opus）＋ Codex 獨立（2026-10-06 本 session 找不到 codex 外掛；若仍缺，改派第二個獨立 Opus deep-reasoner，並在 §8 記下） | 決策提案 → 擁有者確認 Q1–Q4 |
| A | 四項決定：IME、F5、Ctrl+S（含缺陷 3 文案）、legacy 同意 | Sonnet | 紅→綠、§6 日誌 |
| B | 阻擋缺陷 1（必須在步驟 13 之前：目前只有存檔會清 `pending_edits`，先寫存檔測試會把舊語意寫死） | Sonnet（依 Stage 0 定案） | 紅→綠、umbrella 新階段 |
| C | 步驟 13：存檔守衛、`save`／`save_as` UI 測試、重編號後 undo | Sonnet | 紅→綠 |
| D | 小缺陷 4–7 | Sonnet 寫紅燈與規格；Haiku 做機械修改 | 紅→綠 |
| V1 | 審查：plan-code-reviewer＋對抗探針（出廠預設）＋ Codex 同儕 | Opus／Codex | 缺陷清單；有阻擋則回 A–D |
| E | 步驟 15 視覺驗收（6× 裁切、pilot 比對、Poppler、`/verify`）＋使用者實機 IME 驗收 | Sonnet 產圖、Opus 看圖、使用者實機 | 驗收表 |
| F | 步驟 16 文件、codegraph、完整套件 | Sonnet 起草 35 條 PITFALLS（一行候選展開成 Area/Symptom/Cause/Fix/File 是判斷工作）、Haiku 插入＋索引重生＋codegraph、Sonnet（ARCHITECTURE 等）、Opus 終審 | 完成 |

## 5. 各階段細節

### Stage 0（唯讀）

1. **缺陷 1**。事實：閘門在 `model/pdf_text_edit.py:1802,1893` 讀 `model.pending_edits`；`model/text_commit/preview.py:54,298`
   在 session 開啟時凍結旗標；`model/pdf_model.py:3701 _maybe_garbage_collect` 只在存檔或 `edit_count % 5 == 0` 清；
   `docs/ARCHITECTURE.md:1006` 說明閘門存在的理由（兩個引擎不得在未整理的頁交錯）。要回答：
   - 什麼時機清 pending 是安全的？候選：(a) 請求 Tier 0 plan 前對該頁做頁級 `clean_contents` ＋ 重建索引；(b) 復原 legacy 改寫時清掉；
     (c) preview session 每次請求重算旗標而非開啟時凍結。
   - `clean_contents` 之後 Tier 0 的 splice／指紋在 14 個 fixture 上是否仍成立（Office PDF 的 BDC/EMC、TJ 結構）。
   - 文案「請稍後再試」不實，過渡期要改成真話。
2. **IME** 拆兩半：
   - (a) 邏輯（離屏可測）：`InlineTextEditor`（`view/text_editing.py:340`）覆寫 `inputMethodEvent` 追蹤 preedit；
     finalize chokepoint 與 `has_unapplied_input`（`view/text_editing.py:2536`）把非空 preedit 視為未套用輸入——
     KEEP 類原因拒絕並保留；CLOSE_ALWAYS 類原因可見捨棄，**絕不** commit「少了 preedit 的文字」；組字期間 generation bump、Apply 停用、徽章明示「組字中」。
   - (b) 顯示（錄影：preedit 看不見，按 Enter 才出現）。兩個假設，Stage 0 要分辨，修法完全不同：
     - A：proxy 內的 QTextEdit 沒收到 preedit 事件。`view/` 內沒有 `WA_InputMethodEnabled`／`ItemAcceptsInputMethod`／`inputMethodQuery`（grep 零命中），
       但這是弱證據——QTextEdit 自己會設 `WA_InputMethodEnabled`，`QGraphicsProxyWidget.setWidget` 會設 `ItemAcceptsInputMethod`。
     - B：編輯框是 `PreviewBackedInlineTextEditor`（`view/text_editing.py:854`），plan 預覽／覆蓋層由 `toPlainText()` 建立，本來就不含 preedit，所以組字中的字永遠畫不出來。
       handoff 的修法方向「組字期間預覽要含 preedit 或明示」指向這裡。
     離屏驗不到，列為使用者實機驗收（Stage E），用 handoff 的 `ecc-dwg.pdf` 重現步驟。
3. **F5**：修點在 `controller/pdf_controller.py:1247 enter_fullscreen`——finalize 必須是第一句並在 REFUSED 時 return；
   目前 `_cancel_search`、快照、`set_mode("browse")` 都跑在 `cancel_interaction_for_fullscreen`（`view/pdf_view.py:1073`，發 MODE_SWITCH）之前。
   新 reason 加入 `_KEEP_EDITOR_REASONS`，`test_every_finalize_reason_has_exactly_one_policy` 自動涵蓋。
   回歸面：`test_scripts/test_multi_tab_plan.py` 約 20 個 `isFullScreen()` 斷言。
4. **邊界普查**：列出每個進入／離開編輯框的路徑（finalize reason × 輸入狀態 {空、未驗證、被拒、有 token、組字中}），標出已有測試與缺口，作為 Stage A–D 的紅燈矩陣。
5. 缺陷 12（`test_files/test-complexed-layout.pdf` 首 span 改一字 → `no_source_match`）：只做調查與分類，不新增 case_id。

### Stage A（Sonnet；每項先紅後綠）

- A1 IME（離屏；`test_text_commit_ui_real_corpus.py:1549` 既有紅燈保留為閘門）：preedit 中 Apply／點外面／FOCUS_OUTSIDE／Ctrl+S → 保留、0 request；
  preedit 後 commit string → 文字含兩段、新 token；preedit 中 MODE_SWITCH／SESSION_SWITCH → 可見捨棄、PDF 不變；preedit 期間 Apply 停用、徽章文案。
- A2 F5：被拒／未驗證輸入 → 編輯框與輸入保留、不進全螢幕、提示；有 token → 依 Q4；空編輯框 → 照常進全螢幕。
- A3 Ctrl+S／另存：`_save` 與 `_save_as` 分開測三種狀態（token／被拒／預覽中），文案依實際狀態（修缺陷 3：`_kept_notice` 只看 `already_refused`）。
- A4 legacy：`engine=legacy` 跨頁移動無 `allow_rebuild` → 拒絕 `cross_page_move_requires_rebuild`；同意後拒絕 → `FALLBACK_DECLINED`；0 model 呼叫。

### Stage B（Sonnet；依 Stage 0 定案）

紅燈：新增文字框 → 同頁改既有文字 → COMMITTED；同意重建 → 同頁另一行 → COMMITTED；復原新增 → 編輯 → COMMITTED；
已開著的編輯框在旗標清除後拿得到 token。umbrella 加一個「先新增／重建、再改同頁」階段，14 案例全跑。

### Stage C（Sonnet）

- `model/tools/manager.py:132`／`model/tools/watermark_tool.py:110 prepare_doc_for_save` 對 `fidelity_protected_pages` 的守衛（擴充 `test_text_commit_maintenance.py`，不重複）。
- UI 端 `save`（增量）與 `save_as`（完整）各一條，存檔重開後語意比對。
- 完整存檔重編 xref 後 undo：Tier 0 反向重放以頁為鍵，不以 xref 為鍵。

### Stage D

- 缺陷 7：`sig_add_textbox` 字級 `int`→`float`（Sonnet 先寫 10.5 紅燈；Haiku 改 signal 與接收端）。
- 缺陷 5：Ctrl+滾輪重複 toast，同 reason＋文案在保留期間只出一次（Sonnet 規格，Haiku 實作）。
- 缺陷 6：同意框與降級 toast 的 `tier0:...` 代碼一律經 `view/text_edit_reasons.py` 轉白話。

### Stage V1（審查）

plan-code-reviewer（Opus）跑 `/code-review high` 並對照本檔 §1；對抗探針沿用 part 4 方法（出廠預設、真 QTest、spy legacy／add_textbox／同意框）；
Codex 獨立審同一 diff。阻擋級缺陷回對應階段修，再審。

### Stage E（步驟 15）

Sonnet 以副本對 14 案例做前後 6× 裁切輸出到 scratch，Opus 用 Read 看圖與 `_evidence_pilot/*` 輸出比對；Poppler 經 `PDF_EDITOR_PDFTOPPM`；
使用者在實機以輸入法重做 handoff 的 ecc-dwg 流程（「專案」→「示範」→ 點外面），確認 preedit 可見且不遺失。

### Stage F（步驟 16）

Sonnet 先把母計畫 §6 的 35 條一行候選展開成完整條目（含 file:line），Haiku 逐字插入 ＋ `python scripts/build_pitfalls_index.py` ＋ `python .codegraph/indexer.py`。
Sonnet：`docs/ARCHITECTURE.md`（7 參數 `sig_add_textbox`、三組 finalize 原因集合、`_plan_preview_applies`、出廠預設、本輪新 reason 與 IME 處理）、
`docs/FEATURES.md:65`、`docs/架構.txt:117`、`TODOS.md`。Opus 終審；完整套件分批。

## 6. 流程規則（每個 subagent／workflow prompt 開頭的 RULES 前言）

- 禁止 taskkill／pkill／Stop-Process；一次只跑一個 pytest：`.venv\Scripts\python.exe -m pytest …`，不可裸 `pytest`。
- 只在副本上測 PDF；不改 `test_files/` 與 `_evidence_pilot/` 的原檔。
- 先寫紅燈、跑、貼失敗輸出，再實作；紅燈輸出寫進母計畫 §6。
- 步驟 16 之前不改 `docs/PITFALLS.md`、`docs/ARCHITECTURE.md`、`TODOS.md`。
- 不 commit、不 push、不開 PR；tracked 檔案不可含機器路徑或主機名。
- prompt 必須貼上使用者的授權原文句（part 1 的 Poppler／umbrella 階段就是因為缺這句被拒）。

授權原文：
- 規劃授權（2026-10-06）：「plan how to build part 5 to fulfill goal: cover every edge cases; orchestrate opus, sonnet, haiku in advance」
- 實作授權（2026-10-06，已取得）：「開始 part 5，問題照你預設的解，暫不使用 Codex」——此句原文填進 `args.authorization`。Q1–Q4 依 §3 預設讀法，不再逐題詢問。

## 7. 工作流程腳本與續跑

腳本：`plans/true-text-ui-part5.workflow.js`（LF、正斜線）。分三次呼叫，每次之間由人決定：

1. `args.stage = "analyze"`：Stage 0（兩個獨立 deep-reasoner，唯讀，序列）。
2. `args.stage = "implement"`，`args.decisions = {q1, q2, q3, q4}`，`args.design = {ime_logic, ime_display, fullscreen, gaps}`，`args.authorization = "<原句>"`：A → B → C → D → V1，序列執行。
3. `args.stage = "finish"`：E（產圖）→ F。

續跑：被額度上限打斷時，`Workflow({scriptPath, resumeFromRunId, args: 同一份})`；只在失敗的階段 prompt 加續跑說明，其餘不改（改了就失去快取）。
先 `TaskStop` 舊 run。結果以 `<transcriptDir>/journal.jsonl` 為準。

## 8. 決策紀錄

- 2026-10-06：缺陷 1 排在步驟 13 之前（理由見 §4 表）。
- 2026-10-06：IME 拆「邏輯（離屏）」與「顯示（實機）」兩半，後者列使用者驗收，不以離屏測試宣稱修好。
- 2026-10-06：legacy 豁免只有一處，照擁有者決定拿掉，不擴大。
- 2026-10-06：腳本無法在本機語法檢查（沒有 node）；第一次 `Workflow` 啟動即是檢查。
- 2026-10-06：擁有者說「暫不使用 Codex」。Stage 0 第二份獨立分析改派第二個 Opus deep-reasoner（風險優先視角，不看第一份）；V1 不派 Codex。
- 2026-10-06：擁有者授權 Q1–Q4 照 §3 預設。Q3 由主對話綜合兩份 Stage 0 分析定案（兩份不一致時取「不改變 fixture 上 Tier 0 行為」的選項並記下分歧）；Q4 以 `test_text_commit_finalize_policy.py` 的縮放測試斷言為準。
- 2026-10-06：`implement` 另收 `args.design`（IME 邏輯／顯示、F5 對照、邊界矩陣缺口），每個缺口須有紅燈或在 found_not_fixed 說明。IME 顯示若為假設 B（離屏可用 QInputMethodEvent 測），併入 A1。

## 9. 死路

（待填）

## 10. 日誌

- 2026-10-06：計畫建立；尚未開始任何實作。
- 2026-10-06：擁有者說開始。Stage 0 啟動 wf_94ba0982-218（兩個 deep-reasoner，序列）。
- 2026-10-06：換機後 umbrella 基準。原本 `FFFFF`＋逾時，原因是本機沒有 Poppler（七個產品階段全過，只有 second_renderer 失敗）。
  以 winget 使用者範圍安裝 Poppler 25.07.0；系統 VC++ 執行階段 14.32 太舊，算繪 segfault，把 PySide6 附的 14.44 DLL 放到 Poppler 目錄後正常。
  路徑只經 shell 環境變數 `PDF_EDITOR_PDFTOPPM`（workflow 以 `args.pdftoppm` 傳入）。結果：14 passed、1 failed（既有 IME 紅燈），457 s。
  `test_security_packaging.py` 失敗是 venv 沒有 setuptools，屬環境問題，不在本輪範圍。
- 2026-10-06：Stage E／F 紀錄（細節見母計畫 §6 同日條目）。Stage E：14/14 案例 6 倍裁切（MuPDF＋Poppler）UI 階段全過、非目標差異 0、目標差異 > 0；擁有者實機 IME 驗收仍欠（完成標準 5 未滿足）。
  Stage F：ARCHITECTURE（新增 §10.2）、FEATURES、架構.txt、TODOS（9 項既有缺陷）更新；ruff／mypy／lint-imports／device-guard 皆乾淨。
  完整套件：批 1 `1780 passed, 5 xfailed`；批 2 在 `test_page_reorder.py:159` 原生中止（單獨 20 passed，已知順序相依）；批 2a 卡在約 37%，需擁有者決定是否終止；umbrella 本階段未重跑。
- 2026-10-06：Stage E／F 收尾（細節在母計畫 §6「part 5 Stage E／F」）。Stage E：14 案例 6x 前後裁切，MuPDF 非目標差異 0/0、Poppler 非目標 0／目標 >0、UI 階段全 pass。
  Stage F：ARCHITECTURE（新 §10.2＋維護政策段改寫）、FEATURES、架構.txt、TODOS（9 項未修缺陷）已更新；PITFALLS 41 條與索引為先前階段所插。
  閘門 ruff／mypy／lint-imports／device-guard 全綠。完整套件：`test_text_commit_*` 1780 passed 5 xfailed；其餘 test_scripts 無失敗（整批曾遇 `test_page_reorder` 原生中止與一次 0 CPU 掛起，皆非決定性，拆檔後 1068＋1991 passed）；umbrella＋page_reorder 39 passed。
- 2026-10-06：**part 5 整體尚未完成**：§1 完成標準 5 的擁有者實機 IME 驗收（`ecc-dwg.pdf`）仍欠。另有一個掛住的 pytest 行程待人決定是否 `TaskStop`（規則禁止自行終止）。
- 2026-10-06：Stage E 與 pilot 輸出的比對（由 deep-reasoner 讀 56 張裁圖與 8 張 pilot render-after.png；最終審查沒看到這份結果，所以補記）。
  14/14 案例字型、位置、鄰近內容肉眼一致，MuPDF 與 Poppler 只有反鋸齒差異。可用的 pilot 基準只有 `20260924_1431`、`1453`、`1612`（`save_reopen_pass`）；`1959_ui_flow` 是 `ui_blocked`，`1453/case-10-deepen` 改成 "Tank Buf"，皆不採用。
  六個案例沒有 pilot 基準（hvac p4 show6／7／18／26、p6 show7、ecc p0 show60），只靠 Stage E 前後裁圖與非目標差異。位置判定是目視，不是數值 bbox 比對。ecc p0 show60 裁圖含原文，不得進版控。
  掛住的 pytest（PID 1504）已不存在；掛住的位置是 `test_no_jump_editor_geometry.py::test_reopen_same_textbox_cycles_do_not_cumulate_shrink[colored]`（單獨跑通過，非決定性，原因未查）。拆檔重跑後完整套件無失敗。
  最終審查 ship-with-fixes：程式無阻擋；完成標準 5 只差擁有者實機 IME 驗收。

- 2026-10-06：**final-review fix-ups（8 項）已完成，先紅後綠**，細節與紅綠輸出見母計畫 §6「part 5 final-review fix-ups」。(1) undo／redo 重新定位只在「去 xref 頁面指紋」相等時成立（`renumber_invariant_page_fingerprint`），否則 `STALE_UNDO` 零變動，且全程例外安全；(2) `SnapshotCommand` 簿記由 `DocSnapshot`＋`MaintenanceBook` 在 `_capture_doc_snapshot` 單點帶著走，undo／redo 皆還原，`AddTextboxCommand` 併入；(3)(4)(5) 組字文案、legacy 預覽繪製與晶片省略；(6) `fallback_chain_reason_text` 取最後一個拒絕步驟；(7) 存檔失敗也使預覽 session 失效；(8) 存檔守衛不再解碼未變動的受保護 stream（`hvac-dwg.pdf` 50 頁全保護：4440.7 → 62.1 ms）。閘門：ruff、mypy、lint-imports 全過；`test_scripts` 全部（不含 `test_security_packaging.py`）無失敗，umbrella 19 passed。完成標準 5（擁有者實機 IME 驗收）仍欠。

- 2026-10-06：**round-3 小修（round-2 對抗審查）已完成，先紅後綠**，細節與紅綠輸出見母計畫 §6「part 5 round-3 fixes」。N1：`renumber_invariant_page_fingerprint` 只略過間接參照的 `/P`，OCMD 的 `/P /AnyOn|/AllOff` 現在會進指紋（`ocmd_policy` 兩種模式皆 `STALE_UNDO`、零變更）。N2：未重新定位路徑在第一次 `apply_patchset` 前捕捉 stream 儲存，`update_stream` 寫完才丟例外時還原。N7：`_check_hook` 丟非違規例外時 `_abandon`（還原、關 clone）後再丟。N3／N4／N5／N6 只改文件與 TODOS（WatermarkTool 實測為前置 `q`＋原 stream 連續＋後置 `Q`＋平衡疊圖，收緊規則不可禁止前綴）。閘門：ruff／mypy／lint-imports 全綠；persistence 等四檔 88 passed；`test_text_commit_*`（不含 umbrella）1825 passed 5 xfailed；umbrella 19 passed。完成標準 5 的擁有者實機 IME 驗收仍欠。

- 2026-10-06：**round 4（實機 IME 驗收修正）R4-1～R4-5 已完成，先紅後綠**，紅綠輸出見母計畫 §6「2026-10-06 part 5 round 4 (real-IME acceptance fixes)」。R4-1 被拒絕預覽改畫晶片＋「無法套用」徽章並補 `viewport().update()`；R4-2 行內動作列 `view/text_inline_action_bar.py`（viewport 子 widget、`WA_NoMousePropagation`＋`Qt.NoFocus`）取代右側欄按鈕；R4-3 點擊／組字／Esc 提示；R4-4 同模式 `set_mode` 重入不捨棄、右鍵「編輯文字」在自己的 run 上保留編輯框；R4-5 慢速拒絕重繪測試（無產品碼變更）。審查 must-fix：視窗 resize 後動作列以舊位置擺放（事件過濾器順序），已補 `QTimer.singleShot(0, …)` 再定位。
  Finish 階段閘門：ruff／mypy（55 檔）／lint-imports（4 kept）乾淨；`test_text_commit_*`（不含 umbrella）`1858 passed, 5 xfailed`；umbrella `19 passed`（574 s）；`test_no_jump_editor_geometry.py` 單獨 `377 passed, 6 skipped`；`test_page_reorder.py` 單獨 `20 passed`；其餘 test_scripts（209 檔，不含 `test_security_packaging.py`）分四批 `534 passed 2 skipped`／`514 passed`／`398 passed`，第二批在 `test_pdf_merge_workflow.py::test_save_merged_copy_uses_model_external_persistence_policy` 原生中止（`Fatal Python error: Aborted`，順序相依，非 round 4 造成；該檔單獨 `13 passed`，批內其餘 8 檔 `78 passed 4 skipped`）。文件（ARCHITECTURE §10.2、FEATURES、架構.txt、PITFALLS 五條＋索引、TODOS）已同步。擁有者實機 IME 再驗收仍欠。
  離線截圖（不進 repo）：組字中、被拒絕（動作列顯示原因與「改用重建文字…」）、已驗證（套用可用）。

- 2026-10-07：**round 5（影片 2、3：重建後復原使頁面失去圖層身分；影片 3 的 F2 無提示）已完成，先紅後綠**，根因、修法、測試見本檔 §12，紅綠輸出見母計畫 §6「2026-10-07 part 5 round 5」。頁面快照改為頁面物件圖並依 xref 原位還原（`model/page_snapshot.py`，`PDFModel.xref_epoch`），F2 同模式重入新增只通知的提示。審查 must-fix 兩項（redo 鏈跨整份快照指令：擴 xref 表、`SnapshotCommand` 蓋 live epoch）已修。
  Finish 階段閘門：ruff 乾淨；lint-imports 4 kept, 0 broken；mypy（venv 的 mypy 2.1.0 被本機應用程式控制原則封鎖，`ImportError: DLL load failed while importing base64`，非 CI 同一指令）改用純 Python mypy 1.17.1：56 檔無問題；`test_text_commit_*`（不含 umbrella）`1867 passed, 5 xfailed`；umbrella `19 passed`（579 s）；`test_no_jump_editor_geometry.py` 單獨 `377 passed, 6 skipped`；`test_page_reorder.py` 單獨 `20 passed`；`test_pdf_merge_workflow.py` 單獨 `13 passed`；其餘 test_scripts（209 檔，不含 `test_security_packaging.py`）分四批 `469 passed 2 skipped`／`787 passed 9 skipped`／`428 passed 4 skipped`／`637 passed`，無失敗、無原生中止。文件（ARCHITECTURE、FEATURES、架構.txt、PITFALLS 兩條新增＋索引 436 條、TODOS）已同步，程式圖已重建。擁有者實機再驗收仍欠。

## 11. Round 4：擁有者實機 IME 驗收失敗後的修正（2026-10-06）

狀態：R4-1～R4-5 已完成並通過閘門（見 §10 同日日誌）；實機再驗收仍欠擁有者。

擁有者用新注音在 `ecc-dwg.pdf` 副本上實機驗收，未通過（錄影已拆成畫格放在 session scratchpad，不進 repo）。Fable 與 Opus 各自獨立診斷，結論一致：IME 事件本身正常；輸入的「點擊頁面」不在子集字型內，因此預覽拒絕，這是正確的；但介面有下列缺陷，擁有者因此「看不到打的字、找不到套用、什麼都沒發生」。

擁有者授權（原文）：「請修復所有問題 ultracode」。擁有者補充（原文）：「我是在已經是編輯文字模式時再按 F2 沒錯，因為沒有看到打下去的字反映出來所以就按按看。」「我認為套用按鈕應該是要附著在編輯框旁，而不是在右側欄。」

修正項（每項先紅後綠；紅燈可從 scratchpad 的 `debug_fable/test_ime_probe.py`、`debug_opus/test_ime_probe.py` 剪下）：

- R4-1 繪製：plan 模式下，預覽被拒絕後 `_paint_plan_mode_frame` 只畫凍結原文，輸入的字消失（`text_editing.py` `plan_preview_pending`／`_paint_plan_mode_frame`）。改為沿用晶片＋徽章機制顯示輸入文字與「無法套用」徽章；不得退回 CSS 預覽（`test_text_commit_plan_preview_no_css.py` 的不變量）。`set_plan_preview_state` 必須 `viewport().update()`，避免殘留「預覽更新中」。
- R4-2 行內動作列：套用、取消、拒絕原因、「改用重建文字…」從右側欄移到附著在編輯框旁的行內動作列（viewport 子 widget 疊層，不是 scene 內的 proxy，不隨縮放變形，不參與點擊判定）。按鈕 `Qt.NoFocus`，點擊不讓編輯框失焦，也不觸發 FOCUS_OUTSIDE 或 CLICK_AWAY；組字中按套用走既有的組字拒絕。動作列跟隨捲動、縮放、F5、連續模式重建等所有編輯框重新定位或重建路徑，且不得改變編輯框本身的幾何（`test_no_jump_editor_geometry.py`）。屬性名稱 `text_apply_btn` 等維持不變，改指向行內元件。右側欄只留字型、字級、選取粒度。
- R4-3 提示：無驗證預覽時點擊頁面（CLICK_AWAY／FOCUS_OUTSIDE）要顯示一次原因提示，比照 VIEW_RESCALE 去重；組字中的保留提示要寫出被取消的動作（全螢幕／縮放／點擊）；有改動時按 Escape 關閉要顯示一次「已捨棄」提示。
- R4-4 模式重入：`set_mode(目前模式)`（F2、F1、功能區）不再以 MODE_SWITCH 結束編輯；右鍵「編輯文字」作用在編輯框自己的 run 上時保留編輯框，不捨棄後重開。真正切換到其他模式仍照 A1 規則處理。

完成標準：每項的紅燈與綠燈輸出貼進母計畫 §6；ruff、mypy、lint-imports 乾淨；`test_text_commit_*`、umbrella（`PDF_EDITOR_PDFTOPPM` 只放在 shell）、finalize_matrix 全綠；`test_no_jump_editor_geometry.py` 單獨跑全綠；附一張離線截圖，顯示被拒絕狀態下的動作列；ARCHITECTURE、FEATURES、PITFALLS 與索引、TODOS 同步更新。擁有者修正後要再做一次實機驗收（用同一行原有的字重排，例如「標新設」→「設新標」；另打一次缺字，確認動作列出現原因與「改用重建文字…」）。不提交。

## 12. Round 5（2026-10-07）：復原還原保留圖層身分＋F2 提示

狀態：程式與測試完成，閘門結果見 §10 同日日誌；擁有者實機再驗收仍欠。紅綠輸出見母計畫 §6「2026-10-07 part 5 round 5 (undo restore keeps layer bindings; F2 notice)」。

擁有者授權（原文）：「請定位問題並修復 ultracode」。擁有者回報（原文）：「"螢幕錄製 2026-10-07 095350.mp4" 是打缺字，如預期無法套用只能重建。但是 "螢幕錄製 2026-10-07 095453.mp4" 只用原本的文字重排(打上"設新")，竟也是無法套用只能重建，且宣稱圖層結構不支援原位修改。 "螢幕錄製 2026-10-07 095631.mp4" 是打原本的文字("新")，接著依序試點頁面、F2、F5、Ctrl+滾輪、按兩次 Escape，其中 F2 沒有造成任何變化也沒有跳出任何提示，其他的都是提示圖層結構不支援原位修改」。

### 目標

1. 影片 2、3：在影片 1（缺字重建）之後的頁面，用頁面原有的字重排必須能原位（Tier 0）提交，不得出現「圖層結構不支援原位修改」。
2. 影片 3：同模式 F2 在編輯框有無法套用的輸入時要有提示，不可像死鍵。

### 根因（第 1 點）

不是分類器的問題，分類器是對的：頁面在復原之後真的不一樣了。影片 1 的重建被復原（Ctrl+Z）時，`PDFModel._restore_page_from_snapshot` 用 `insert_pdf` 把「單頁 PDF 快照」嫁接回來再 `delete_page`。`insert_pdf` 嫁接的是所有被頁面引用的間接物件的「複本」：頁面物件換了 xref；`/Properties` 指向複製出來的 OCG，而 `/OCProperties` 只列原本的 OCG，所以 `ecc-dwg.pdf` 第 1 頁 320 個 wrapper 全部由 `oc_layer_visible_default` 變成 `props_unresolved`，於是每次真文字編輯都被 `mc_wrapper_not_pure_layer` 拒絕。同一條路還遺失 `/VP`、`/StructParents`（struct `/Pg` 懸空）、TOC 目的地與 Popup 註解，每次 undo／redo 多約 100 個物件；擷取端 `insert_pdf` 也會抹掉 live 註解的 `/P`。存檔後的影響：非 secure 存檔留下孤兒 OCG 複本（圖層面板與該頁脫鉤）、字型重複、`/VP`／標籤／書籤損壞；garbage=4 只會把 OCG 與字型複本合併回去。

### 修法

單一咽喉：`model/page_snapshot.py`（`PageSnapshot`、`capture_page_graph`、`restore_page_graph`、`PageSnapshotStale`）。快照是頁面物件圖（從頁面物件走所有可達間接物件，不往上走 `/Parent`／結構 `/P`、不進其他頁、頁樹、catalog；預算 10 萬物件），還原依 xref「原位」寫回（非根物件先、頁面物件最後；stream 位元組先於 stream 字典），沒有任何 graft 後備。`PDFModel.xref_epoch` 標示快照所屬編號世代：live doc 以 garbage>=2 序列化會重編號並遞增世代（`_note_live_doc_serialized`），保持編號的安裝路徑還原原世代。世代不符、頁面 xref／`xref_length`／`/Parent`／stream 型別不符時，在任何寫入前拋 `PageSnapshotStale`，`EditTextCommand`／`AddTextboxCommand` 的 undo／redo 以零變動拒絕（沿用既有拒絕提示）。審查修補：gate (c) 不再拒絕超出 xref 表的記錄而是擴表（整份 `SnapshotCommand` 的 redo 會讓表變短）；`SnapshotCommand.__init__` 以 `_stamp_live_epoch` 對裸 bytes 的 `after`（controller 的合併）蓋上 live 世代。分類器與 `_NOT_REBUILDABLE` 一律不動。

F2：`TextEditManager.notify_same_mode_reentry()` 只通知不 finalize（finalize 等同 click-away，違反 R4-4），以 `editor._reentry_notice_stamp` 獨立去重，不讀寫 `_pointer_notice_stamp`；由 `PDFView.set_mode` 的同模式分支與 `_start_text_edit_from_hit` 的自己 run 分支呼叫。

### 測試

- `test_scripts/test_page_snapshot_identity.py`（30）：頁面／OCG／字型／註解身分、`/VP`、`/StructParents`、TOC、Popup、壞寫入回滾、stale gate、epoch 各安裝路徑、擴表、redo 鏈（highlight／rotate x rebuild／textbox）、合併裸 bytes。
- `test_scripts/test_text_commit_undo_restore_identity.py`（3，真實 app＋`ecc-dwg` 副本）：重建後復原再重排，commit Tier 0；擴張被拒為 `growth_region_not_blank`，不是 `mc_wrapper_not_pure_layer`。
- `test_scripts/test_text_commit_finalize_policy.py` 6 個新測（4 紅、2 guard）：F2 說明一次、click-away 後 F2 再說、組字中、右鍵「編輯文字」。

### 死路與取捨

- 放寬分類器或把 `mc_*` 加進 `_NOT_REBUILDABLE`：禁止，頁面真的變了，那是掩蓋症狀。
- 保留 `insert_pdf` 當後備：後備本身就是誤貼 bug，已移除；擷取失敗現在丟錯而不是退成整份快照。
- 以 `_pointer_notice_stamp` 去重 F2 提示：擁有者先點過頁面，會被靜音。
- 取捨：secure 存檔之後 rebuild／textbox 的 undo／redo 被拒（過去默默失去身分）；TODOS 有「存檔時重映射快照」。擷取成本在密集頁約 2-46 ms／次。
- 未修：已存檔的舊損壞無法回溯修復；`render_page_pixmap` overlay 路徑仍對 live 註解 `/P` 有 `insert_pdf` 副作用；本機 venv 的 mypy 被應用程式控制原則封鎖（用純 Python mypy 1.17.1 替代：56 檔無問題）。

## 13. Round 6（2026-10-07）：plan 模式看不到游標／選取、編輯框內點擊誤移框、存檔暴增

狀態：程式與測試完成，閘門結果見母計畫 §6「2026-10-07 part 5 round 6」；擁有者實機再驗收（真 Windows IME）仍欠。不提交。

擁有者授權（原文）：「more than 1 problem, please position & fix ultracode」。常設授權（原文）：「請修復所有問題 ultracode」。擁有者在 `ecc-dwg.pdf` 副本上的錄影顯示三個問題：（P1）plan 預覽模式下沒有游標、沒有選取、打的字看不清楚；（P2）在已開啟的編輯框內點一下（手有抖動），框被移動約 14 px，並以 `geometry_override_present` 拒絕未改動的文字；（P3）一個 222 KB 的檔案在「重建 + Ctrl+Z + Ctrl+S」之後存成 5.9 MB。診斷與設計由獨立的 designer／critic 完成，主 session 決議見 session scratchpad `r6/decisions.md`（不進 repo）。

### 目標

1. P1：打字時看得到游標、選取與組字，字夠大、不會在隱形的第二行。
2. P2：框內點擊／拖曳是游標與選取；移動框要有明確的握把；抖動的點擊不得移框、不得讓未改動文字無法套用。
3. P3：非 secure 存檔不再寫出復原與保留的重建留下的孤兒物件；重建嵌入的字型不再以原始 5 MB TTF 存進檔案。

### 根因

- P1（四個疊加）：plan 模式的 `paintEvent` 從不呼叫 `QTextEdit.paintEvent`（只畫光柵＋徽章＋晶片），所以 Qt 的游標與選取永遠畫不出來；游標本來就設 `setCursorWidth(0)` 且 IME 輸入從不 reveal；stylesheet 的 `selection-background-color` 是全透明；隱藏版面用替代字型（CJK 1.0 em，PDF 字型 0.835 em）會折行且逐字 x 與光柵對不上（214% 縮放時第 4 字差約 18 px），Home／Up／Down 在看不見的行間移動。晶片只有 9–10 px 且被省略號截斷。
- P2：框內的按下一律被當成「移框拖曳」的起點，門檻固定 3 px，低於平台拖曳距離，手抖就越過；同一個按下也不放游標。
- P3（三個獨立原因）：(A) Story 把整個系統字型（`kaiu.ttf` 5,181,580 bytes）原樣、不壓縮、不子集化地嵌入，加上 272,265 bytes 的 raw ToUnicode，且每次 `insert_htmlbox` 一份新複本；(B) 重建的 redaction 讓 `can_save_incrementally()` 變 0，存檔走 `_full_save_to_path` 的 `garbage=0` 完整重寫（母計畫先前假設是增量，實測只有一個 `%%EOF`）；(C) 復原的 `restore_page_graph` 只寫回快照記錄，不清理 live 文件裡的孤兒（xref 108..120，5,678,929 stream bytes）。實測 live doc 序列化：`garbage=0` 5,902,003、`garbage=1` 221,600、`garbage=4` 221,340。

### 修法

- P3a 存檔剪枝（`model/save_compaction.py`、`PDFModel`）：非 secure 完整存檔一律 `garbage=1`（保留編號、不動 live doc、epoch 不變，所以存檔後的 undo／redo 仍可用）；增量存檔前 `_session_orphans_block_incremental`：本 session 新增（`persisted_xref_length` 以上）且不可達的 stream 合計 >= `ORPHAN_FALLBACK_MIN_BYTES`（64 KiB）就改走剪枝的完整存檔，較小的（`apply_pending_redactions` 的小串流）維持增量；水位在開檔／存檔重開／增量成功後記錄，未知則走安全的完整存檔，`xref_length() == 水位` 跳過掃描；可達性 BFS 由 `/Root`、`/Info`、`/Encrypt` 出發，以 `xref_length()` 為界。secure 路徑（`garbage>=4`）不變。
- P3b 字型壓縮（`model/font_stream_compaction.py`）：`font_compaction_scope(doc)` 包住 legacy edit_text（所有策略、垂直重試、push-down）與 add_textbox／文字框移動／旋轉；正常結束時合併相同的新 `FontFile*`／`ToUnicode`（解碼位元組雜湊、只動水位以上）並各 Flate 壓縮一次，`/Length1-3` 原樣還原；`insert_htmlbox_tracked` 是 model 內唯一的 `insert_htmlbox` 咽喉（範圍外會丟錯，`scratch=True` 例外），AST 測試把守。scope 在指令的 after-snapshot 之前關閉；tiered 引擎不開 scope。只壓縮，不子集化。
- P2（view 層）：框內左鍵＝游標／選取（Shift 延伸、雙擊選詞、右鍵不動），hit-test 走編輯器文件版面並含捲動位移；`EditorMoveGrip`（`⠿ 移動`）是唯一的移框方式，edit_text 與 add_text 皆有；拖曳門檻 `max(3, startDragDistance())`（視埠像素）；組字中按框內或 strip 會先 `commit_ime_composition`（`commit()`，仍組字則 `reset()`）再放游標；I-beam 由 view 在每次移動時自己設定，teardown／`set_mode` 時還原。
- P1（view 層）：`view/text_live_strip.py` 的 `LiveTextStrip` 是行內動作列第一列（編輯框外的 UI chrome，`Qt.NoFocus`）：可讀鏡像（>= 14 px、最多 6 行）、游標（編輯器有焦點時可見）、選取帶、組字底線，同步鏡像；點擊／拖曳／Shift+點擊移動編輯器游標；`composition_changed` 新訊號；`inputMethodEvent` 會 `reveal_caret()`；IME 錨點是 strip 游標（動作列隱藏時退回編輯框）；plan 與 run 模式隱藏版面 `NoWrap`。晶片與徽章不動（Round 7 已移除 plan 模式晶片，見 §14）。
- Review 後修補：`test_19ac_...cross_page_move_roundtrips_via_document_undo_redo` 改為拖曳移動握把；`test_a_failure_inside_compaction_never_fails_the_operation` 不再依賴 caplog（其他測試模組在收集時 `logging.disable(CRITICAL)`），改 spy `fsc.logger.warning`；IME `commit()` 在 Windows 可能是 no-op，改用 `commit_ime_composition`（`commit()` 後仍組字則 `reset()`）；`_LINE_SEPARATOR` 改寫成 `" "` 跳脫；移動握把無移動分支還原視埠游標。

### 測試

- `test_save_prunes_orphans.py`（24）、`test_font_stream_compaction.py`（27）、`test_text_commit_editor_mouse_gestures.py`（36＋2 個 IME reset 測試）、`test_text_commit_live_text_strip.py`（38）；真實 app（`ecc-dwg` 副本、shipped defaults）：`test_rebuild_undo_save_writes_no_orphans_and_redo_survives`、`test_kept_rebuild_save_has_no_rebuild_leftovers`、兩個 P2 owner-run 測試、兩個 P1 ecc 測試；`test_text_editing_gui_regressions.py` 兩個新測取代 `test_small_drag_can_activate_editor_move`。
- 紅燈（各階段 `scratchpad/r6/logs/p3a_red*.txt`、`p3b_red.txt`、`p2_red*.txt`、`p1_red.txt`、`mf_ime_red.txt`）：P3a 23 failed／1 passed（真實 app 紅燈量到 `saved 6126947 bytes from an original of 222884`，與擁有者的量測相同）；P3b 27／27 failed；P2 28 failed／10 passed；P1 33 failed／4 passed。

### 死路與取捨

- 在復原時把指令新建的物件 `update_object(x, "null")`：拒絕，PyMuPDF `doc.InsertedImages`（雜湊到 xref 的快取）會把已被 null 的 xref 再發給下一次相同圖片的 `insert_image`；改在存檔時剪枝（只動序列化副本）。
- 重建時 latch `secure_save_required`（`garbage=4`）：拒絕，會重編號並遞增 epoch，存檔後所有頁面快照 undo 失效。
- 存檔 `deflate=True`：拒絕，會重新編碼原檔的內容串流與字型。
- `doc.subset_fonts()`：拒絕，會改寫原檔字型（xref 8、67 由 40,726 增為 214,442、46,798 增為 177,698 bytes），破壞位元組一致；子集化需 `fontTools`，等擁有者釘版（TODOS）。
- 把增量存檔一律改為完整存檔：拒絕，`clean_contents` 一定留下小孤兒，為此放棄 append-only 修訂不划算；採 64 KiB 門檻（兩側都有測試）。
- 以框內的 Qt 版面畫游標：拒絕，版面（替代字型）與光柵對不上，且待處理／被拒的文字沒有光柵可對。光柵對齊的框內游標列為後續（TODOS：逐字幾何要經 DTO 帶到 view）。
- 取捨：strip 以螢幕字型顯示打的字（不是 PDF 字型），並與晶片重複（Round 7 已移除 plan 模式晶片，見 §14）；P4（重建出來的行在巢狀 form XObject 內，被切成 4 個 run）不修，記在 TODOS；旋轉頁的 `_clamp_editor_pos_to_page`／`editing_rect` 既有 bug 因握把成為唯一移框方式而更顯眼，列 TODOS；一次增量存檔寫入的孤兒會留在水位以下直到完整存檔。
- 未做：`capture_worker_snapshot_bytes` 改 `garbage=1`（每次搜尋／OCR／列印快照都會多一次可達性掃描，未量測，故不做）。

### 狀態

閘門：ruff、lint-imports（4 kept）、mypy（純 Python 替代，58 檔無問題）與各測試批次見母計畫 §6 同日日誌。擁有者實機再驗收（真 Windows IME；項目見 TODOS「Owner real-app re-acceptance (round 6)」）仍欠。

## 14. Round 7（2026-10-08）：移框後原文字重影、移除 plan 模式框內晶片、旋轉頁移框

### 目標
- F1：S17a 以握把移動既有文字後，原位置不得再看到原字（不得出現「備備為C標新設。」）。
- F2：擁有者決定移除框內晶片；徽章保留；即時文字列為輸入文字與組字的唯一顯示。實作範圍見「死路與取捨」：只在 plan 模式移除，非 plan 的組字晶片是唯一的組字顯示，保留。
- ROT：/Rotate 90/180/270 頁面以握把移框不得跳動，editing_rect 必須正確（TODOS「Rotated-page box move」，已結案）。

### 根因
- F1：單一遮罩項目隨框移動（`_update_editor_drag` -> `refresh_text_editor_mask_color` -> `setRect`），開框矩形失去遮蓋；遮罩為對比度染色（灰字 145 -> 202 灰），不能複製筆刷。診斷：`scratchpad/r7/diag_f1.md`。
- F2：晶片早於即時文字列；非 plan 編輯器組字時晶片是唯一的組字顯示（列只在 plan 模式出現）。診斷：`diag_f2.md`。
- ROT：開框時 proxy 繞 (0,0) 旋轉，pos 位於框的角（90：x1；180：x0+W, y0+H；270：y1）；`_clamp_editor_pos_to_page` 與 `_finish_editor_drag` 把 pos 當左上角。診斷：`diag_rot.md`。

### 修法
實作順序 ROT -> F1 -> F2（F1 動到 ROT 改過的拖曳程式）。決定檔：`scratchpad/r7/decisions.md`（critique R2/R3/R4/R5 與 M1–M8 納入）。
- ROT（`view/text_editing.py`、`view/pdf_view.py`）：新增模組層級 `_proxy_corner_offset`、`_proxy_visual_extent`、`_quarter_turn_proxy_layout`。開框的正向公式維持字面（`x0 + sr.x1`、`y0 + sr.y1`，開框位置與舊版位元組相同；決定 R2），反向才用 helper：`_finish_editor_drag` 減去 `_proxy_corner_offset`（旋轉 0 短路、不碰 widget）、`_clamp_editor_pos_to_page` 以旋轉後的視覺框夾限、`_resolve_editor_page_idx_for_drag` 以視覺中心換頁判斷。旋轉取自 `view._editing_rotation`（不用 `proxy.rotation()`，假 proxy 的 rotation 是屬性）。正向與反向因此是兩份程式，靠測試互相把守，不是「構造上互逆」。`_compute_editor_proxy_layout` 未動。
- F1（`view/text_editing.py`、`view/pdf_view.py`）：第二個項目 `_text_editor_origin_mask_item`（z 10.5，高於 hover 10、低於移動中遮罩 11／proxy 12／邊框 13），範圍為原文字 span `_editing_origin_span_scene_rect`（開框時由原頁 scene 原點 + `_editing_original_rect` * 縮放算出，視覺頁座標、與旋轉無關；Round 1 REG-1 修正，原本誤用編輯框 widget 的 `_editing_origin_scene_rect`）外加 1 pt 邊界（`_ORIGIN_MASK_MARGIN_PT`，至少 1 scene px），以 `toAlignedRect()` 向外取整，僅 edit_existing 且框位移 > 0.5 px（`_ORIGIN_MASK_MIN_DISPLACEMENT_PX`，位移判斷仍比對 widget 矩形 `_editing_origin_scene_rect`）時惰性建立，顏色為原頁環形取樣平均、不染色（`tint=False`、不讀 `text_rgb`，決定 R5）；環形取樣與快取簽章用 span，沒有 span 就不畫；環形不均勻比例超過 0.05 時不畫（Round 1 RPU-2，見下）。框移回即隱藏；跨頁後仍蓋原頁，原頁重新渲染時重新取樣（`_maybe_refresh_editor_mask_for_page` 也更新 `_editing_origin_page_idx`）；`scene.clear()` 前先 detach；`_teardown_editor` 移除並刪除快照；新增文字不建立。單一入口 `sync_text_editor_origin_mask`，由 `refresh_text_editor_mask_color` 兩條路徑呼叫。
- F2（`view/text_editing.py`，`PreviewBackedInlineTextEditor`）：刪除 `plan_preview_chip_text`；`_paint_plan_overlay` 改名 `_paint_editor_overlay`，畫完徽章後在 `self._plan_mode or not self._preedit_text` 時直接返回（plan 模式不畫任何晶片）；非 plan 的組字晶片本體保留。`_composing_chip_parts`、`elide_composing_parts`、`_fit_edge` 仍有呼叫者，保留。

### 測試（先紅後綠；紅燈 log 在 `scratchpad/r7/logs/`）
RED = 實作前失敗，GUARD = 實作前後都通過（對照用）。每個新測試至少有一個 RED id。
**ROT**（`ROT_red_unit.txt`、`ROT_red_mvc.txt`、`ROT_red_m2_finish_disabled.txt`、`ROT_swapped_rows_sensitivity.txt`；綠 `ROT_green_unit.txt`、`ROT_green_mvc_final.txt`）
- `test_text_editor_rotated_move.py`（21 個，全 RED，無 GUARD；`AttributeError: _quarter_turn_proxy_layout`）：`byte_identical_to_pre_refactor_literals[0|90|180|270 x 1.0|2.14]`（硬編碼舊版字面公式，M1 i）、`corner_offset_matches_literal_forward_corner[同上]`、`visual_extent_matches_rotated_proxy[0|90|180|270]`（對真 `QGraphicsProxyWidget`）、`drag_page_resolution_uses_the_rotated_box_centre`（行為紅：得頁 1，應為 0）。
- `test_text_commit_editor_mouse_gestures.py`（真 MVC）：
  - `test_move_grip_drag_moves_the_editor[axis-rot]`（重寫）：RED x/y-90、180、270；GUARD x-0、y-0。
  - `test_the_proxy_box_is_at_editing_rect_at_open_and_after_a_grip_move`（M1 ii）：RED 90、180、270；GUARD 0。
  - `test_a_small_first_grip_move_never_jumps_the_box`：RED 90、180；GUARD 0、270。
  - `test_grip_drag_clamps_the_rotated_box_inside_the_page[dir-rot]`：RED left-90/180、right-90/180/270、up-180/270、down-90/180/270；GUARD left-0、left-270、right-0、up-0、up-90、down-0。
  - `test_grip_round_trip_restores_editing_rect_on_rotated_pages`：RED 90、180、270；GUARD 0。
  - `test_a_rotated_grip_move_lands_where_the_box_was_dropped_and_survives_save_reopen`（M2）：RED 90、180、270（先以 ink bbox 度量紅，改度量後停用 `_finish_editor_drag` 的反推再證一次紅）；GUARD 0。移框 -> rebuild-consent apply -> 另存副本重開，皆比對。
  - `test_grip_moves_an_add_text_box_on_a_rotated_page_by_the_drag`（審查 S5）：四個旋轉全為 GUARD（程式已修好，補覆蓋）。
- M1 敏感度：暫時對調 `_proxy_corner_offset` 的 90/270 兩列 -> 12 個失敗（corner_offset[90|270 x 兩種縮放]、move_grip_drag_moves[x|y-90|270]、proxy_box_is_at[90|270]、round_trip[90|270]），0/180 通過；檔案已還原位元組相同。
**F1**（`F1_red_mvc.txt`、`F1_red_unit.txt`、`F1_red_tab.txt`、`F1_red_ecc.txt`、`F1_red_m5_origin_refresh_disabled.txt`、`F1_red_margin0.txt`；綠 `F1_green_*.txt`）。灰字 0.57（rgb 145）使染色階梯生效，前提以 `mask_debug_metrics` 的 `tint_strength > 0` 斷言。
- `test_grip_move_hides_the_source_text_at_its_old_spot[0|90|180|270]`：RED 全四（開框矩形內 912／911／912／912 個偏色像素；前提：框確實離開原位）。檢查：內部 == 原頁環形平均（±2）、中心像素 == 頁面底色（不是 202）、矩形外 3 px 環乾淨（M3/M4）。
- `test_grip_move_back_hides_the_origin_patch[0]`：RED（無補片屬性）。`test_escape_after_a_grip_move_removes_the_origin_patch[0]`、`test_scene_detach_takes_the_origin_patch_out_of_the_scene[0]`、`test_a_refused_zoom_keeps_the_origin_patch[0]`（M7）、`test_a_committed_move_removes_the_origin_patch[0]`（M6 i，rebuild-consent apply）：皆 RED（前提：補片不存在）。
- `test_cross_page_grip_move_keeps_the_origin_page_covered[0]`（含 M5 原頁重新渲染重新取樣）：RED；M5 部分另以停用 `_maybe_refresh_editor_mask_for_page` 的原頁分支證紅（顏色停在 (255,255,255) 而非 (255,250,200)）。
- `test_add_text_grip_move_leaves_no_origin_patch[0]`：GUARD。
- `test_grip_move_leaves_no_source_glyph_or_sliver_on_the_owner_run[100%|214%]`（ecc-dwg 副本，needs_fixtures；M3）：RED 兩個（sync 改成 no-op 時於補片前提 AttributeError）。審查 S1：邊界強制為 0 時 `[0|90|180|270]` 四個 id 與兩個 ecc id 共 6/6 RED（環內殘留墨跡 2／2／2／2／9／32，`F1_red_margin0.txt`），邊界因此有失敗的 run 把守。
- `test_text_editing_gui_regressions.py`：`test_background_matched_mask_without_tint_keeps_the_page_colour` RED（`TypeError: tint`）；`test_origin_patch_is_created_only_for_a_displaced_edit_existing_box` RED（AttributeError）；`test_origin_patch_is_never_created_for_add_new_or_without_a_page_sample` RED（AttributeError；add_new 一半近似 GUARD，但整個測試需要新方法）。
- `test_multi_tab_plan.py::test_19acb_origin_patch_of_a_moved_box_does_not_survive_a_tab_switch`（M6 ii）：RED（前提：補片不存在）。
- M3 量測（ecc-dwg.pdf 副本，CJK run「備為C標新設。」，無邊界，移框後）：100 % 時開框矩形上方 1 px 有墨（9 px，偏差至多 43）、下方 1 px（6 px，至多 23），距離 2..6 乾淨；214 % 時上方 1..2 px（1 px：29 px 至多 55；2 px：10 px 至多 47；3 px 偏差 5，不可見）；合成 Helvetica 頁下方距離 1 有 2 px、偏差 3..4（不可見）。故補片 = 開框矩形 + 1 pt（= max(1, render_scale) scene px）邊界。
**F2**（`F2_red_unit.txt`、`F2_red_policy.txt`；綠 `F2_green_unit.txt`、`F2_green_policy.txt`）
- `test_text_commit_plan_preview_no_css.py::test_plan_mode_paints_the_badge_and_no_chip[pending|refused|composing_unchanged|composing_typed]`（設計測試 14）：RED 全四（左下帶有晶片像素）；另斷言 `not hasattr(editor, "plan_preview_chip_text")`。
- `test_non_plan_composing_still_paints_the_preedit_chip`（設計測試 15）：GUARD。
- `test_text_commit_finalize_policy.py::test_a_plan_mode_box_paints_no_chip_while_composing[False|True]`（M8 b，真 app，框抓圖左下帶 == 組字前抓圖）：RED 兩個（121 個晶片像素）。帶為最後 12 列 x 左 1/4 欄（真編輯框在縮放 1 時僅 80 x 12 px，設計的「高 >= 30」不成立；另斷言 `w - w//4 >= 40` 以避開右上徽章）。
- `test_a_preedit_is_visible_in_the_editor_paint[False|True]`（既有、重寫）：GUARD（strip 檢查前後皆通過）。

**刻意改動的既有測試（需擁有者簽核；同 TODOS）**
- `test_move_grip_drag_moves_the_editor`（重寫：四種旋轉、兩軸，移除 90 度特例與旋轉守衛）；mouse_gestures 的 fixture 重構（`_gui_session`、`_write_page(gray, pages)`、`gui`／`gui_grey`／`gui_grey_two_pages`）、`_open_ecc_run_at` 併入 `_open_ecc_run(monkeypatch, tmp_path, zoom=None)`、新增 `_ALL_ROTATIONS`（`_ROTATIONS` 不動）。
- `test_finalize_text_edit_removes_mask_item`：另植入原位補片，並斷言它被移除並重設。
- `test_text_commit_plan_preview_no_css.py`：模組 docstring；`test_pending_paints_frozen_frame_badge_and_chip` -> `..._frame_and_badge`；`test_verified_raster_paints_without_badge_then_stays_as_last_frame` 移除晶片文字斷言；`test_composing_chip_paints_the_elided_parts_...` 改 plan_mode=False 並 `_regenerate_preview()`＋`_mutated_preview_is_valid` 斷言；`test_refused_preview_paints_the_typed_text_chip_and_a_refusal_badge` -> `test_refused_preview_paints_the_refusal_badge_over_the_base`。
- `test_text_commit_finalize_policy.py::test_a_preedit_is_visible_in_the_editor_paint`：晶片文字斷言換成 strip 的 `preedit_area()` 檢查。
- `test_text_commit_real_ime_round4.py`：兩個名稱／docstring（一個改名 `..._repaints_the_refusal_badge`）；`test_text_commit_live_text_strip.py`：一則註解。
- 注意：mouse_gestures、live_text_strip、real_ime_round4 是未追蹤的 round 6 檔，沒有 git 基準，審查只以測試名稱對照 round 6 閘門 log，未逐本體 diff。

### 死路與取捨
- 遮罩擴成新舊兩框的聯集：拒絕，一次環形取樣會混兩處背景，且染色灰塊會露出。
- 複製移動中遮罩的筆刷：拒絕，染色後是灰色（202），在白頁上可見。
- 補片恰為 span 本身、不加邊界：拒絕，CJK 墨跡超出 span bbox 1–2 px 會留下殘影（見 M3 量測）；代價是邊界可能暫時蓋掉貼邊 1 pt 內的鄰近向量內容（表格線、底線），框回位／提交／取消後恢復，列入擁有者驗收。
- 補片蓋整個開框矩形（編輯框 widget）：Round 1 證實是錯的（REG-1），widget 在旋轉 0／180 至少 80 px 寬，會抹掉同基線的鄰近文字；位移判斷用 widget 矩形、遮蓋範圍用 span。
- 正向與反向共用同一個 helper（設計原案）：改為正向維持字面（R2），開框位置位元組相同；互逆性由測試把守（字面公式測試、真 Qt scene 框檢查、對調列敏感度）。
- 全面移除組字晶片：範圍縮為 plan 模式（critique R1 選項 b）。非 plan（新增文字、legacy）組字時 `LiveTextStrip` 隱藏、晶片是唯一的組字顯示。後續選項 a1（擁有者決定，TODOS）：非 plan 編輯器整個生命週期顯示 strip，IME 錨點才不會跳動，之後再刪晶片。
- 用 `proxy.rotation()` 取旋轉：拒絕，假 proxy 的 rotation 是屬性；用 `view._editing_rotation`。
- 刪除 `_drag_pending` mouse-move 死分支：本輪不做（決定），只讓它呼叫已修的 clamp；TODOS 保留該行。
- 跨不同 /Rotate 頁面的移動：未處理（既有，TODOS）。
- 審查 S2（未解）：移框後重建，合成單行 Helvetica 文字回來變窄且分成兩行（旋轉 0 也是），M2 因此只比對第一行左上角錨點（unrotated frame）。因不能 checkout／stash，無法在乾淨基準確認是否既有；列 TODOS。

### 狀態
- 各鄰近套件逐一通過（Round 1 修正之前的數字；之後見下方 Round 1 小節）：rotated_move 21、mouse_gestures 91（含 ecc needs_fixtures 兩個）、gui_regressions 63、plan_preview_no_css 23、finalize_policy 98、real_ime_round4 9、live_text_strip 38、multi_tab_plan 74（1 skipped）、no_jump_editor_geometry 377（6 skipped）、text_geometry_page_rotation 26、text_edit_rotated_page_gui 12、add_text_intent 9、continuous_centering 4；`ruff check .` 通過。獨立審查結論 accept、無 must_fix（`scratchpad/r7/review.md`）。
- 本文件步驟未執行：全套件、mypy 平價、`r6/manual/run_manual.py` S17a 離線手動 run；結果以閘門步驟的 log 為準。
- 擁有者實機再驗收欠：S17a（ecc-dwg 副本，100 %／214 %，含先打 點 再移框、含貼著表格線的 run）、plan 模式真 IME 無晶片只有 strip 組字與徽章、90/270 頁移框。

### Round 1 adversarial review（2026-10-09）
審查者對 round 7 的未提交程式做對抗式審查，回報 5 筆發現（`scratchpad/r7/round1_findings.json`：R7-REG-1、CS1、B1、RPU-1、RPU-2）；RPU-1 與 R7-REG-1 是同一個缺陷（補片用 widget 矩形而非 span），合併為 REG-1。每筆先由獨立的重現步驟驗證（暫時測試，驗完移出 repo；記錄 `scratchpad/r7/repro/round1_<id>.md` + `.log` + `test_zz_r7_repro_*.py`），4 筆驗證為真，皆已修。

**角度**：`round1_findings.json` 沒有逐項記錄審查角度，以下是依發現性質的歸類，不是原始角度清單。
- 補片遮蓋範圍（遮到不該遮的鄰近內容）：REG-1／RPU-1（與既有 S4 的 1 pt 邊界不同，這是 widget 對 span 的差距，可達 50 px 以上）。
- 補片顏色（背景不均勻時的外觀）：RPU-2。
- 拖曳生命週期與 finalize 的交錯（保留型 finalize 打斷進行中的拖曳）：CS1。
- 各層對「是否移動」的門檻不一致（0.5 scene px／0.5 pt／0.01 pt 與像素取整）：B1。

**發現與結果**（嚴重度為審查者所評）

| id | 嚴重度 | 缺陷 | 重現結果 | 修法 |
|---|---|---|---|---|
| REG-1（含 RPU-1） | medium | 補片蓋 widget 矩形（>= 80 px 寬），同基線的 `NEIGHBOUR` 在補片內的墨跡 115 -> 0 個暗像素；補片 82 x 16 對 span 18.7 | VALID | 新快照 `_editing_origin_span_scene_rect`；遮蓋、取樣、簽章用 span + 1 pt，`toAlignedRect()` 向外取整；位移判斷仍用 widget 矩形；無 span 不畫 |
| CS1 | low | 拖曳中遇保留型 finalize（`SAVE_SHORTCUT`、`VIEW_RESCALE`）：拖曳狀態被清掉，`editing_rect` 停在原位而框與補片在新位置，Apply 會套回舊位置；游標停在 ClosedHand（重現：位置停在 +40 而非 +60） | VALID | `finalize_text_edit_impl` 對非 discard 理由先以 `view._on_move_grip_finished(QPoint())` 結束拖曳，再算 delta；`QPoint` 加入 import |
| B1 | medium | 框拖出再拖回原位：`editing_rect` 差 0.047–0.056 pt（四個旋轉皆然，旋轉 0 證明早於 round 7），預覽以 `geometry_override_present` 被拒、Apply 停用 | VALID | `_finish_editor_drag`：scene 邊界矩形與 `_editing_origin_scene_rect` 在 0.5 scene px 內且在原頁時，`editing_rect` 還原為 `_editing_original_rect` 的精確副本 |
| RPU-2 | medium | 補片是單一環形平均色，條紋背景上成為平坦灰塊（131，亮度標準差 0.00，周圍 79.7） | VALID | `_qimage_ring_nonuniform_ratio`；`ring_nonuniform_pct` > 0.05 時不畫補片並快取判定（`_origin_mask_skip_signature`） |

重現數字摘要：REG-1 見上表；CS1 `editing_rect` = 原矩形、補片可見、游標 ClosedHand；B1 四個旋轉 proxy 位置完全一致、容差 0.5 pt 未被超過，真正失敗的是 `_emit`（0.01 pt）與模型的 override 檢查；RPU-2 補片內標準差 0.00、外圍 79.66。

**紅綠 log**（`scratchpad/r7/logs/`）
- REG-1：紅 `r1_REG-1_red.txt`（`test_origin_patch_covers_the_source_span_not_the_editor_widget[0|90|180|270]`：RED 0 與 180，GUARD 90 與 270，因旋轉 90/270 時 widget 本來就等於 span）；綠 `r1_REG-1_green.txt`（mouse_gestures 95 passed）；鄰近 `r1_REG-1_nb_*.txt`。第一次用未取整的分數 span 時，兩個 ecc-dwg 與跨頁測試失敗（邊緣像素殘影），改 `toAlignedRect()` 後通過。
- CS1：紅 `r1_CS1_red.txt`、綠 `r1_CS1_green.txt`（`test_a_keep_finalize_mid_grip_drag_completes_the_drag[SAVE_SHORTCUT|VIEW_RESCALE x 0/90/180/270]`，8 passed）；鄰近 `r1_CS1_nb_*.txt`。
- B1：紅 `r1_B1_red.txt`（`test_grip_out_and_back_to_the_open_position_restores_the_exact_rect_and_keeps_apply[0|90|180|270]`，4/4 RED）、綠 `r1_B1_green.txt`（8 passed，含 GUARD `test_grip_out_and_a_little_back_keeps_the_inverse_rect[0|90|180|270]`：離開放位置 3 px 仍是移動，修前後皆通過）；鄰近 `r1_B1_nb_*.txt`。第一版比對 `proxy.pos()`，在 90/180/270 失敗（pos 是角、origin 矩形是 sceneBoundingRect），改比對 scene 邊界矩形；gui_regressions 曾因假 proxy 缺 `sceneBoundingRect` 失敗一次，以 `getattr` 守衛修好。
- RPU-2：紅 `r1_RPU-2_red.txt`、綠 `r1_RPU-2_green.txt`（mouse_gestures 113 passed）、量測 `r1_RPU-2_probe.txt`；測試 `test_origin_patch_is_not_painted_over_a_striped_background[0]`、`test_ring_nonuniform_ratio_separates_flat_rings_from_hatching`。門檻量測（3 px 環）：合成白頁 0.000、ecc-dwg CJK run 0.0033（100 %）／0.0040（214 %）、1 pt 條紋 1.000；0.05 比語料高 12 倍以上。
- 最終驗證（逐一執行）：`r1_verify_*.txt`——mouse_gestures 113、rotated_move 21、gui_regressions 63、plan_preview_no_css 23、finalize_policy 98、multi_tab_plan 74（1 skipped）、text_edit_rotated_page_gui 12、no_jump_editor_geometry 377（6 skipped）、live_text_strip 38；`ruff check .` 通過。無原生中止。finalize_policy 那次 shell 回傳碼 127，但 log 內 98 passed、沒有 FAILED／ERROR／Fatal 字樣，判為 shell 假象、未重跑。

**揭露（紅燈證據的限制）**
- RPU-2 的紅燈是在實作之後才補的：門檻需要先量測才能選，閘門先寫了；之後把 `_ORIGIN_MASK_MAX_RING_NONUNIFORM_PCT` 設成 2.0（閘門關閉）證明條紋測試會失敗（補片存在），再還原 0.05（grep 確認）。單元測試 `test_ring_nonuniform_ratio_...` 的紅燈只是 helper 尚不存在。不是嚴格的先紅後綠。
- CS1 的紅燈先斷言游標（仍是 ClosedHand）而失敗，所以紅燈 log 本身沒有顯示 `editing_rect` 斷言失敗；`editing_rect` 未更新是由重現記錄（修前）證明的。

**留下的缺口**（TODOS）：背景重建（非均勻背景上原文字會留在框旁直到提交或取消）；穿過 span 的規線或稀疏網底低於門檻，仍會被平坦補片抹掉；非 grip 的 body 拖曳也會經 `_on_move_grip_finished` 結束（未測，grip 是唯一的移動者）；非 plan 的組字晶片後續（選項 a1）；為此輪刻意改動的既有測試待簽核（含 Round 1 新增的 `_expected_origin_cover` 取代 widget 矩形 + 邊界、gui_regressions 假 view 的 `_editing_origin_span_scene_rect`）。本小節未執行：全套件、mypy 平價、離線 S17a 手動 run。
