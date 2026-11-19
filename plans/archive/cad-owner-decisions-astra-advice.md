2026-11-18 · 主代理 Codex（執行環境未揭露確切型號／effort，不冒稱 Astra）；reader gpt-6.1-terra/medium、deep-reasoner gpt-6.1-sol/xhigh、reviewer gpt-6.1-sol/high · HEAD `504e6c0db8cd475cefbe085cabb3f0efc98f5779`（不含既有 A5 未提交修改）· 建議順序 D1 > D12 > D4 > D9 > D10 > D3 > D6 > D2 > D11 > D7 > D5 > D8
| ID | recommended option | confidence | needs owner word | blocks A5 commit |
|---|---|---|---|---|
| D1 | c：文件 handle 世代 + 清理 | high | yes | yes |
| D2 | a：忠實回報未能完成分析 | high | yes | yes |
| D3 | a：zoom 不取消 pending | high | no | yes |
| D4 | a：整批先解析，再一次交易 | high | no | yes |
| D5 | c：明示平台不支援，另卡處理移植 | high | yes | no |
| D6 | 現在修：pending 隱藏物件操作 | high | no | yes |
| D7 | 保留，補入卡片及邊界測試 | high | yes | yes |
| D8 | c：獨立快照背景建索引 + 重用 | medium | yes | no |
| D9 | new：明確 zlib level 1 壓縮 splice | medium | yes | yes |
| D10 | new：延後到真正使用時查 placements | medium | yes | yes |
| D11 | 依 kind 顯示影像分析訊息 | high | no | yes |
| D12 | 有界整組 admission；失敗依文件隔離 | high | yes | yes |

## 調查邊界與交接狀態

本文件是給 Opus 的決策建議，不是 owner 裁決，也不是 A5 完工或 H23 整段程式審查。只新增本檔；既有程式、測試、handoff 的修改全部保留。來源調查與設計分析串行執行。Opus 是尚待完成的外部獨立同儕：先重跑關鍵量測，逐項標 agreed / disagreed / needs-more，再取得必要裁決。本文的 reviewer 只審本建議，不代替外部同儕。

表中「blocks A5 commit」指建議的提交前條件，不代表 owner 已增訂 gate。D8 不阻止 A5 修正單獨提交，但阻止宣告完整 M0 達標與開始 Track B；D5 的平台範圍要先由 owner 明確接受。所有量測均為當前 dirty tree 的 PyMuPDF 1.27.1；不是只對 HEAD 的結果。微量測為單次樣本，不是 GUI heartbeat，不能據此刪除 KNOWN_OVER_LIMIT。

## D1. Table cache and failed set leak across documents (A3 review B2)

Recommendation: c，使用永不重用的「文件 handle 世代」取代 `id(doc)`，並在 handle 退休時清理該世代的成功／失敗狀態與 pending 工作。

Evidence:
- `model/table_objects.py:43`, `:54`, `:61`, `:152`, `:173`：外層為 model 弱鍵，內層 frame 使用 `id(doc)`；model 留存而文件換掉時，弱鍵不會救內層舊結果。
- `model/pdf_model.py:1909` 建立 session；`:4885` 的 snapshot restore 到 `:4899` 會換 doc，同一 session 並不等於同一 handle。單用 session UUID + 可回復的 edit_count 不足。
- 完整 production literal 搜尋（measured，命令及輸出在 Appendix C）只找到 `table_objects.py:61` 與 `font_stream_compaction.py:74,87,98`。後者是活躍 context scope 計數，`:104` 的 finally 退出會清除，期間仍持有 doc，不是持久幾何快取。
- A5 `model/content_scan.py:301` 的成功快取以 decoded bytes digest 為鍵；`:303`, `:350` alias 是 raw digest + stream dictionary，不含 doc identity；不應為 D1 全部改成 revision cache，H18 保留。其失敗集合與容量問題另見 D12。
- 破壞性 A→B 誤刪為 handoff `:421` 的歷史重現，本輪未再執行破壞性重現，不標成本輪 measured。

Why not the others:
- a：只清 open/close 遺漏 restore、repair、roundtrip 換 handle，也難保晚到 child answer。
- b：世代解決身份，但不單獨解決舊集合長期增長；兩者一起做，清理是回收機制，世代是正確性防線。

Change it implies:
- `PDFModel` 的文件安裝／替換 chokepoint、`close_session`、`_restore_doc_from_snapshot`、`_roundtrip_live_doc`；`table_objects.frame_key`、coordinator stale-answer check 必須共用同一身份，不能各自計數。正常切換既存 tab 不生成新世代，真正換 handle 才生成。
- H3 before: `A cache of page geometry is keyed on (id(doc), page_num, edit_count, len(doc), page.rotation, tuple(page.cropbox), tuple(page.mediabox)).`
- H3 after（待 owner）: `Replace id(doc) with a process-unique document-handle generation assigned whenever a live handle is installed or replaced. Retire only that generation's geometry, failures and pending ownership; retain the remaining frame fields.`
- Red first：`test_table_objects.py::test_frame_identity_survives_forced_id_reuse`，確定性強制 identity collision，A 的 table 與 failed 不得出現在 B；`test_object_probe.py::test_old_answer_after_snapshot_replacement_is_dropped`；包含同 session undo/redo、tab 切換、close/open 及 stale-table delete 不改 B bytes。

Risks: 忘記替換入口會留下同類錯誤；先列出所有 doc assignment，再以替換測試參數化覆蓋。不要全域清空其他 tab 的純內容成功快取。

## D2. resource_limited is unreachable inside find_tables (A3 review B1)

Recommendation: a，保留可證明的 `MemoryError → resource_limited`，`find_tables() is None → analysis_failed`；訊息只說分析未完成，不推測一定是記憶體耗盡。

Evidence:
- installed `.venv/Lib/site-packages/pymupdf/table.py:2720`：`except Exception as e:`，記錄後 `return None`；`src/object_probe/helper_main.py:105` 只特判 Python MemoryError。
- measured：Appendix B 在真實 128 MiB Job Object cap 內，300 MB native allocation 失敗；為了測函式的 catch 邊界，將這個真 allocation 注入 `table.make_edges`，不是自然耗盡的 CAD table fixture。原始輸出節錄：

```text
before {"ok": true, "peak_commit": 44802048, "cap": 134217728}
native FzErrorSystem False code=2: malloc (300000000 bytes) failed
after_native {"ok": true, "peak_commit": 44802048, "cap": 134217728}
find_tables_return None
python MemoryError
```

- allocation 被拒絕不會把已成功配置的 peak 拉到 cap；本例 peak 只有 cap 約 33%。因此「peak 接近 cap 就分類 OOM」無法可靠判別。測的是 commit，不能用 working set 替代。

Why not the others:
- b：目前 accounting heuristic 已被反例否定。Job completion-port 的 limit notification 是否能可靠攜帶每次拒絕，本輪 unmeasured；不能以它作已驗證方案。
- new：解析 stderr 的 `malloc failed` 太依賴版本／字串，最多診斷資訊，不能當 protocol 正確性的依據。

Change it implies:
- A3b item 4 before: `MemoryError → resource_limited.` after（待 owner）: `A Python MemoryError escaping the handler maps to resource_limited. A native allocation error swallowed by find_tables maps to analysis_failed; neither peak usage nor absence of a typed error proves the cause.`
- `controller/pdf_controller.py:3385` 的 generic 訊息建議「此頁的物件分析未完成（第 n 頁）」；診斷 stderr 保留，不把失敗 cache 成空表格。
- 現況基線：`test_object_probe_child_v2.py::test_swallowed_native_allocation_failure_is_analysis_failed`，真受限 child + allocation injection，驗證 JSON、exit 0、無 rects；此 mapping 已存在，預期現在就通過，不冒稱 red test。另測正常 table 成功，避免把所有 None 當資源不足。
- 實際修改的 Red first：`test_payload_memory_error_returns_typed_json` 對 payload read 注入 MemoryError，要求 exit 0、resource_limited、無 rects；現況會逸出。UI 測試 `test_analysis_failed_message_does_not_claim_cause` 要求新「未完成」文案，現況仍為「失敗」。

Risks: 無法對每次 native OOM 給出專屬訊息，但不會誤報原因。另須把 payload reading 納入錯誤邊界（見 New findings N3），否則 MemoryError 仍可能沒有 JSON。

## D3. Zoom cancels a pending click (A3 review N1)

Recommendation: a，分離「重建 scene 時清除視覺選取」與「使用者改變選取而取消 pending」。

Evidence:
- `controller/pdf_controller.py:4790`, `view/pdf_view.py:4080` 的 zoom 重建經 selection clear；`view/object_selection.py:111`, `:286` 增 generation，違反 H4 明文。

Why not the others:
- b：H4 已裁決；沒有證據要求更改使用者語意。

Change it implies:
- 保留 H4；A3 item 5 before: `The generation is incremented ... in _clear_object_selection ...` after: `Generation changes for a semantic selection change, not for scene cleanup caused by scroll/zoom. Preserve the stored page-space point and resolve it against the rebuilt scene.`
- `test_object_probe.py::test_pending_click_survives_continuous_zoom` red：submit→zoom→answer 仍選到同物件；新 press、mode/tab/document change 仍取消，測單頁與 continuous。

Risks: 過度取消 generation increment 會讓新選取被舊 answer 覆蓋；不能只刪除那一行。

## D4. Batch delete runs find_tables on the GUI thread (A3 review N2)

Recommendation: a，在任何 mutation 前解析、驗證整批目標，以不可變的刪除計畫執行原有單一 atomic transaction。

Evidence:
- `controller/pdf_controller.py:3563` 只先做 readiness；`model/pdf_object_ops.py:2444` 每個 table 重新 matching；`:2575` batch 迴圈逐個刪，revision 改變後 `table_objects.py:210` 走 blocking 分析。

Why not the others:
- b：目前本就有 cold preflight；光確認每頁一次 fresh 不會阻止第一刀後的 cache miss。
- 每刀後重建 table cache：違反 H14/H15，也混淆「原始選取目標」和「刪除後重新辨識的表格」。

Change it implies:
- `_delete_object_impl` 接受內部已解析目標；`delete_objects_atomic` 一次凍結 table bboxes／識別並驗證 frame。Controller 遇 cold member 仍 refuse-and-request，不 replay。
- A5 item 5 before: `Batches check every member before any is executed.` after: `Check readiness and resolve every member against one pre-mutation frame before any mutation. Execute frozen targets without table detection, within the existing single rollback/undo transaction.` H14/H15 不改。
- 重疊 table 的語意：刪原始所有選取區域，先去重，不在中途重新找剩餘表格；混合物件仍維持現有排序與不可用目標的整批 rollback。若現有 public API 無法表達，先由 Opus 補內部 plan shape，不新增 UI 語意。
- Red first：`test_object_ops.py::test_batch_tables_never_analyse_after_first_mutation`，第二刀若呼叫 find_tables 就失敗；要求兩表刪除、一個 undo、undo 還原 bytes；加同頁／跨頁、重疊、混合 image/table、空集合、invalid ID、cold member 完全不 mutation。

Risks: 預解析後仍使用會變動的序號會錯刪；計畫必須持有穩定目標內容，不能只存 table index。

## D5. Table select and delete never work off Windows (A3 review N3)

Recommendation: c，M0 明確標示此分析功能目前只支援 Windows；非 Windows 回報平台不支援，移植獨立成卡。

Evidence:
- `src/render_worker/memory.py:118` 非 Windows 回 None，`admission.py:47` 拒絕；更深一層 `src/object_probe/memory_limit.py:78` 明確 `raise ContainmentError("unsupported platform")`。
- `.github/workflows/ci.yml:213` 功能測試 matrix 為 Windows、Ubuntu；`:319` 非 Windows job 為 advisory。沒有 macOS 功能測試 leg；Windows 真 containment 測試有平台 skip，不能把 Ubuntu 綠燈視為實際 child 功能通過。

Why not the others:
- a：只加 memory reader，仍過不了 containment。
- b：固定 cap 的數字不等於 OS 強制 cap；無法守住 H24，且現有 child 仍拒絕。

Change it implies:
- A3b runner item 6 before: `If limit is None ... status: no_headroom` after（待 owner）: `Distinguish unsupported containment platform from transient no_headroom before admission; do not launch an uncontained child.`
- 顯示「此平台尚未支援受記憶體限制保護的物件分析，此功能目前無法使用。」不說稍後重試。H24 Windows hard cap 不改；若 owner 要跨平台，再獨立設計並實測 Linux/macOS containment，不把 RLIMIT 或 working set 類比當已證明等價。
- Red first：`test_object_probe_runner.py::test_unsupported_platform_is_not_no_headroom`；mock 平台 capability，驗證不啟動、不要求稍後重試、不快取空結果。Windows no_headroom 行為保留。

Risks: 這是明確接受功能支援範圍的決策，需 owner word。若 owner 要求本版跨平台可用，本項立即升為 blocker，不能宣稱已修好跨平台。

## D6. Context menu shows Delete Object under the disabled analysing entry

Recommendation: 現在修。`view/pdf_view.py:6378` 到 `:6392` 的 pending 分支應排除所有物件刪除／旋轉項目，保留不依賴分析的一般選單項目，不清除原 selection。A3 已寫「in place of the object entries」，不需改 owner 決策。Red：有舊選取時在新位置 pending，menu 中無可用 Delete Object／Rotate，分析完成也不自動重開 menu。

## D7. Additions beyond the cards (A3 and A3b)

Recommendation: 保留以下項目，請 Opus 將已超出卡片者逐項送 owner 確認，而非一併回退。

| 項目 | 判斷與理由／來源 |
|---|---|
| CropBox restore + exact_set_key | 確認；`table_objects.py:106`–`:123` 恢復 library reset 遺漏的 frame；guard 是既有保真約束。歷史 16 組 parity 為 handoff 記錄，本輪未重跑。 |
| early-answer buffer | 確認；`object_probe_coordinator.py:96`–`:122` 防 submit 內同步拒絕在 job 登記前遺失；需同步成功、拒絕、取消後不殘留測試。 |
| child_v2 測試獨立檔 | 確認；組織方式不改行為；suite 自動發現該檔即可，不需要為命名搬檔。 |
| is_waiting | 確認；coordinator `:71`–`:79` 用以取消排隊舊工作，保留 running job 語意。 |
| runner= 注入 | 確認；`:39`–`:42` 為測試邊界，production 預設仍真 runner。 |
| view 測試替身 fallback | 有條件確認；`object_selection.py:117`–`:124` 只容許缺 controller API 的替身，真產品不得進 blocking fallback；加真 controller routing 測試。 |
| text-edit pending 不吞 press | 確認；`pdf_view.py:4617`–`:4624` 保留文字操作，但不能因此建立 image drag。 |
| Python stdout→stderr | 確認；`helper_main.py:88`–`:91` 保護 JSON stdout；這不等於攔截所有 native stdout，runner 仍須驗證協定。 |

A3b preflight 文字補上「reset 後於 exact_set_key scope 還原 CropBox」；A3 coordinator 補上「submit 內同步 answer 在 job 登記後恰好交付一次」。其餘為 implementation note，不修改 H1/H4/H16。

## D8. Text hit and text index on the GUI thread (A4, plus two A5 gestures)

Recommendation: c，新增 A6「背景文字 hit/index + 同頁提取重用」，排在 A5 修正後、Track B 前；owner 核准前不把此問題當 A5 圖像效能已解決的一部分。

Evidence:
- 1,346–1,437 ms 是 handoff `:427` 的既有 cProfile／heartbeat，未在本輪重測。
- `model/text_block.py:153` 已用同一 textpage 提供 dict/rawdict；不是所有地方完全沒 cache。plain text 另讀，`pdf_model.py:3302` 建 index，`:3447` fallback 再提取。
- `model/page_content_text.py:60`–`:98` 明示 content-only 語意，display-list replay 會改 segmentation；不能用更快但不同文字結果替換。

Why not the others:
- a：背景化若不重用資料，仍有重複工作與 answer 後再次 GUI 提取風險。
- b：一個 cold 解譯本身就可能超過 100 ms，cache 只能改善 warm。
- d：可如實保留 known failures 到 A6 完成，但不能說 M0 Accept 已達標。

Change it implies:
- 新卡 before: `No card covers this`（handoff log）；after（待 owner）: `A6 prepares content-only text hit/index data from an isolated snapshot outside the GUI thread and installs a pure-data result only for an unchanged document generation, revision and page frame; all consumers reuse that result.`
- 優先沿用 one-shot helper（新增 text job 需 H16 schema 設計）；不讓 worker 讀 live fitz doc，也不跨執行緒傳 TextPage。Snapshot 準備、序列化／反序列化、DTO 安裝與首次 resolve 全算進 heartbeat；若 capture 自身超標，A6 不能宣稱完成，需另提出可驗證 snapshot 方案。
- Accept：CAD sample 的 browse right-click 與 form/paths browse，cold 和 warm 都完成且 longest GUI gap ≤100 ms；answer 後不再提取；換頁／zoom／crop／rotation／edit／undo／tab 時舊答案不覆蓋；文字 hit、run IDs、annotations/widgets 排除語意不變。不要藉 unrelated text-edit 模式重設規則。
- Red first：`test_gui_stall.py::test_browse_cold_text_index_is_async` 及 sample driver；`test_text_block.py::test_worker_index_matches_content_only_index` 比較文字與位置 DTO。實際測試檔命名由 Opus 按既有 suite 確認。

Risks: 這是設計卡，不是可立即交機械實作者的完整 DTO／protocol spec。Opus 須先寫清楚 mapping、snapshot 成本與 stale key，再讓實作者動手。

## D9. Deflate cost of the byte splice (A5 Accept item 2)

Recommendation: new，A5 的兩個 splice 共用明確 level-1 zlib writer，保留壓縮串流且避開 PyMuPDF 的最高壓縮成本；不改全域 save 策略，也不放寬 Q1。

Evidence:
- `.venv/Lib/site-packages/pymupdf/__init__.py:7819`, `:21942` 的 `compress` 是 truthy 開關，`:19075` 使用 `FZ_DEFLATE_BEST`；`compress=2` 不是 level 2。
- measured：Appendix A，同一 `_build` 200,000-path fixture，最後一次完整 run 的數字如下；各操作 fresh model + warm scan，暫時替換 Document.update_stream，finally 還原，未改 repo source。這是模型層時間，未包含 controller repaint/undo/GUI heartbeat。

| 寫入模式 | update ms | move / resize / rotate / delete ms | 普通 garbage=1 儲存 bytes（加換行 probe） |
|---|---:|---|---:|
| 現有 compress=1 | 610.272 | 863.496 / 854.394 / 933.803 / 985.915 | 1,405,890 |
| compress=0 | 1.377 | 134.463 / 148.790 / 138.984 / 137.687 | 4,296,546 |
| 明確 zlib level=1 | 63.827 | 169.687 / 173.085 / 200.207 / 211.508 | 1,817,233 |

- 原 fixture 1,405,888 bytes；level1 約增加 29%，raw 約增加 206%。每種操作的實際儲存大小在 Appendix A 原始輸出；decoded save/reopen equality 對 probe 三方案、四種 save flags 都是 true。
- raw + garbage=1 alone 不壓縮；raw + deflate=True 為 1,404,919 bytes、275.913 ms。level1 + deflate=True 仍約 1,816,835 bytes，並未重壓成最高等級；不要承諾一般 save 會自動還原原大小。
- `model/pdf_model.py:4991` `_save_doc` 未要求 deflate；`:4526` serialization 預設亦為 0。因此 raw 延後壓縮是實際的額外儲存設計，並非免費得到。

Why not the others:
- a/c：最快、程式最少，但檔案膨脹與 snapshots 成本較大，若要保證 save 壓回去會擴及現有 save/encryption/incremental 邊界。
- b：公開 update_stream 不提供壓縮 level；本建議自行 zlib 壓縮，明確列為新增選項。
- d：效能瓶頸可避開，沒有理由先改 owner 的 Q1。

Change it implies:
- `model/pdf_object_ops.py:355`, `:897` 使用一個內部 writer，先完成壓縮，再寫 compressed bytes（compress=0），於 exact_set_key 下設 `/Filter /FlateDecode`，移除不相容 `/DecodeParms`。失敗走原本整筆 rollback，不能留下「壓縮 bytes、無 Filter」的半成品。保留無關 dict keys 與 xref；`/Length` 必須由 writer 更新為實際 encoded byte 數，測試須核對，不能要求原 length 不變。不對其他 image/font streams 套此策略。
- A5 item 3 before: `doc.update_stream(xref, new)`；after（待 owner）: `Precompress the decoded splice with zlib level 1, write the encoded bytes without a second compression pass, and set matching stream decoding metadata under the exact-key guard. Preserve decoded bytes, unrelated dictionary keys and transaction rollback.`
- Red first：`test_native_image_probe.py::test_splice_uses_bounded_compression_and_preserves_decode`，驗證不用 default highest compressor；unfiltered、Flate + DecodeParms、含間接 dict key 的 fixture，decoded splice 完全相同；失敗注入於寫 bytes／Filter 之間可 rollback。既有 move/resize/rotate/delete + undo/redo、encrypted save/reopen、xref 字面值保真不可退化。
- Accept：正式 `test_native_image_ops_stall.py` 與 verify driver 中四 edit/undo ≤1 s；保存／重開畫面相同；本次原始 byte equality 不能代替實際視覺驗證。若 level1 在正式路徑不達標或 exact metadata 無法安全維護，改選 raw + 明確接受檔案大小，而不是直接擴大 Q1。

Risks: Filter／DecodeParms 最重要；不得把 plain bytes 標為 Flate，也不得重複壓縮。壓縮程度變更會改 raw stream hash，guard/undo 必須使用真實前後 raw bytes，不期待編碼相同。

## D10. get_image_rects cost (A5 Accept items 1 and 3)

Recommendation: new，延遲取得 placements；只有現有分支真正消費 MuPDF bbox/transform 時才每 xref 查一次，保留全部既有 fallback 幾何。

Evidence:
- `pdf_content_ops.py:401`–`:405` eager 呼叫；`:425`–`:427` direct cm + 有效 page frame 已自行算 bbox，根本不取 placement 座標；`:435` 僅更新 bounded occurrence offset。
- installed `pymupdf/__init__.py:11794`–`:11799` 強制 Pixmap.digest + hashes=True，沒有 hashing-off 參數。
- measured，Appendix A 的 fixture-only perturbation 將 get_image_rects 暫回空 list：images 所有 invocation 欄位與原結果相等，231.122 ms cold /174.855 ms warm →0.764 ms；heavy 86.993/72.137 ms →4.983 ms。這只是兩 fixture 證明查詢多餘，不是可上線的「總回空」實作，也未量測四個完整 GUI gestures。
- `content_scan.py:141`–`:167` 是 last cm by depth，並未建立累積 CTM／clip；不能聲稱 scan 已具備完整 rendering geometry。

Why not the others:
- a：全用 scan 替代 geometry 會擴大 CTM、Form、clip、inline image 的證明範圍。
- b：API 不允許；get_image_info(hashes=False) 沒有等價的 xref matching 保證。
- c：只 cache discovery 無法修 cold 的四個 images gestures，也增加 D1 類 invalidation 面積。
- d：把 hashing 移去 child + page cache 可解較廣的情況，但此次兩個具體 fixture 不需要新增協定／PDF snapshot 成本。

Change it implies:
- `discover_native_image_invocations` 與 `_discover_form_nested_invocations` 共用 lazy placements accessor。未載入時只累加 direct occurrence 計數；首次 fallback 載入時 offset = min(計數, placements 數量)，之後沿用目前 capped increment。必要 fallback：cm 缺失、page frame 無法證明、Form records。每 xref 在同次 discovery 最多載入一次。
- A5 item 2 before: `both loops ... keep their own placement logic`；after（待 owner）: `Keep every existing placement result and occurrence-order rule, but load MuPDF placements only when that branch consumes them; direct cm records in a proven page frame must not call get_image_rects.` H17/H18 不變。
- Red first：`test_native_image_probe.py::test_direct_image_discovery_never_hashes_pixmaps` 對兩 fixture patch get_image_rects→raise；以保留的 eager reference 比較所有 invocation 欄位。加 direct+Form 共用 xref、不同 xref 相同像素、direct 次數大於 placements、缺 cm、無法證明的 page frame、nested q/cm、crop/rotation/UserUnit、clipped/invisible、inline image 保持既有拒絕／忽略語意。
- Accept：四個 images fixture gestures 與 heavy answered click 的真 GUI longest gap ≤100 ms、確實完成，才能移除對應 KNOWN_OVER_LIMIT。這個選項針對已知四 gestures + click；Form/no-cm fallback 的 cold latency 仍 unmeasured，不能宣稱所有 PDF 都達標。

Risks: offset 的 lazy 初始化若只用未截斷計數，fallback 可能漏選或錯對應。不可藉此修正／擴張既有幾何語意；若 parity 反例無法保持，再提 child discovery 卡，而非靜默改成自製 full CTM。

## D11. Message for a scan that ends resource_limited (A5 Accept item 4)

Recommendation: `controller/pdf_controller.py:3385` 改用 kind 分流，scan 顯示「此頁影像分析超出記憶體上限而未完成；此頁的影像目前無法選取或編輯（其他物件不受影響）」。目前為直接中文常數，沒有英文 localization key，不新增翻譯機制。表格保留既有訊息。若 D12 的「record budget」也使用 resource_limited，理由需另帶 `record_budget`，文案改「此頁影像資料超出分析上限而未完成；此頁的影像目前無法選取或編輯」，不可把紀錄數拒絕偽稱 OS 記憶體不足。Red：同一 status 下 tables/scan 各自正確，no_headroom 也不可說成表格；拒絕後不顯示 ready、不讓殘留 selection 繼續編輯。

## D12. A5 implementer's judgement calls

Recommendation: 保留純內容成功快取，改成有界的整組 readiness admission；資源失敗採文件／frame scope，不把暫時失敗當內容本質。

Evidence:
- `content_scan.py:319`–`:330` 容許單項超限；coordinator `:152`–`:166` 依次 store 並直接 emit ready。兩個每份 100,001 筆的結果互相逐出（measured，Appendix C）：

```text
after_store_a_b False True
after_retry_a True False
same_content_other_doc_failed True
```

- 此為合成 cache 資料重現 eviction，不是整個 GUI livelock 的實測；後者由相同 readiness 缺件循環推導，需 red integration test。
- `content_scan.py:304`, `:358` global failure set 與 `pdf_content_ops.py:317` 的 failed-skip 使另一文件的相同 bytes 也消失。成功結果可以共享，資源不足與 containment 失敗不能。

| item | verdict | reason / action |
|---|---|---|
| 1 oversized alone | reject | 既違反 hard cap，又無法解多 stream 輪流逐出；整頁所需 key union admission，容不下給 terminal resource_limited/record_budget，不能 emit ready。 |
| 2 remove 無 Do → ValueError | confirm | helper 的合法輸入就是 Do 或其 q block；保留 invalid range 測試，不把非法 range 猜成成功。 |
| 3 failed keys 在 content_scan | reject as implemented | 問題是 global lifetime；按 document generation + page frame + job key 隔離，換 frame/handle 可重試；同 frame 不自動 retry typed failure。可由 coordinator 管 state，model 查 scoped 狀態；不可全域 digest 貼上失敗標籤。 |
| 4 parser 接受 scans | confirm | 必需 protocol 支援；仍校驗 status、list 長度與 from_json，malformed 不得成功。 |
| 5 image_scan_jobs getattr | conditional confirm | 只為測試替身兼容；production PDFModel 必須具有 callable API，測試不得以 fallback 繞過 cold-edit refusal。 |
| 6 移除 _q_bounds_by_operator_index | confirm | scan 已承接 q bounds；以舊邏輯 reference parity 保護，不保留兩套 production 算法。 |
| 7 unused operator helpers | keep this round | 沒有 A5 correctness 需要刪；獨立 tidy 可處理，避免在診斷修改中增加 API 變動。 |

Why not the others:
- 單純拒絕 store、仍 emit ready：會再次 pending，不能算容量處理。
- 無界保留當前頁：改壞記憶體約束，另有多頁／tab 多份 active 集合問題。

Change it implies:
- A5 item 1 before: `at most 200,000 records in total`；after（待 owner）: `Keep a hard 200,000-record resident budget. Admit the complete required set for a page atomically, evict unrelated entries, and pin it for synchronous ready-resolution or an edit transaction. If the required set cannot fit, emit a terminal resource_limited reason record_budget, with no ready signal.`
- Pin 的界線必須由 Opus 寫成機械步驟：進入同步 resolve/edit 前 acquire，finally release；檢查整組總量後才 deserialize/install 或至少限制接受量；發 ready 前再次驗證 frame 與全部 required keys 存在。不長期 pin 多個 tab。GUI event-loop yield 不可讓半組被使用。
- A5 item 4 before: `keys remembered in failed_scan_keys`；after（待 owner）: `Failures are owned by document generation and page frame; successful StreamScan data remain content-keyed. Changing context permits a fresh request; a typed failure in the same context does not retry automatically.`
- Red first：`test_content_scan.py::test_required_scan_set_admission_is_atomic`（100001+100001、200001、剛好200000、空集合、壞 JSON）；`test_native_image_probe.py::test_overbudget_page_terminates_without_ready_loop`；`test_same_content_new_document_does_not_inherit_failure`；跨 tab、undo/replacement、late answer、derived scan admission 都要涵蓋。

Risks: 200k 是 record 計數，不是 heap bytes 上限；本方案只忠實履行卡片的容量，不能把它當 GUI process hard memory cap。子程序 H24 仍保留。Derived scan 在寫入後超限不能遺失 transaction 所需資料；同樣走保留／拒絕策略，不另開無界例外。

## Challenges to made decisions

- H3 的 `id(doc)` 不能作長期 identity；D1 是由既有破壞性證據支持、等待 owner 的具體替代裁決，未在本輪直接修改。
- A3b item 4 如果被解讀為「任何 cap failure 都會得到 resource_limited」，實測反例推翻；D2 僅修正分類承諾，H24 cap 公式與強制隔離完全保留。
- A3 item 5 literal clear-generation 與 H4 衝突：D3 遵守 H4，改實作卡片的過度概括句，不重新裁決 zoom UX。
- A5 字面 200k hard bound 與 oversized exception 不一致：D12 提 bounded terminal outcome，拒絕偷偷擴大上限。
- Q1、H1、H14/H15、H17/H18、H24 不放寬。沒有建議未經 owner 同意重開已裁決的 strip/clip/no-text-preflight 等事項。

## New findings

- N1（blocks A5 commit: yes，納入 D12）：多 stream 成功結果互相逐出；Appendix C 有最小 cache repro。整個 GUI 重試迴圈尚未實跑，Opus 先補 red integration test。
- N2（blocks A5 commit: yes，納入 D12）：相同內容跨文件共享 operational failure；Appendix C 最小 repro，`pdf_content_ops.py:317` 顯示 lookup 跳過該 stream。這不是 H18 純成功 cache 的錯。
- N3（blocks A5 commit: yes，建議納入 D2 邊界修正）：`helper_main.py:102` `_read_payloads` 在 handler try 外；MemoryError 沒有 typed answer。來源可直接重現：注入 `_read_payloads` 拋 MemoryError 呼叫 main，會逸出目前 try；本輪未執行此注入，標為 source-only。把 payload read 與 handler 放同一 guarded block；超低記憶體下連 JSON 都不能寫的 native crash 仍交 runner，不承諾所有失敗必有 JSON。
- N4（blocks A5 commit: no，fence log / 後續同快取卡）：alias map `content_scan.py:303,355` 不隨 LRU 驅逐，也無 production lifecycle clear 呼叫。重現步驟：反覆 store_scan + store_alias 並觸發 eviction，alias 數繼續增加；source-only，本輪未作壓力測試。它不回傳已逐出 scan，屬成長問題；建議加有界 alias LRU／反向清理，別與 D1 identity leak 混稱。
- N5（blocks A5 commit: no，評估限制）：`test_native_image_ops_stall.py:126` 接受列入 KNOWN_OVER_LIMIT 的超標，pytest exit 0 不等於 A5 Accept。這是已明寫的測試政策，不是新程式 bug；Opus 報告務必列實際 heartbeat 和是否仍有已知超標。

## Opus 執行順序與完成條件

1. 獨立重跑 Appendix A/B/C、核對來源與當前 HEAD/dirty diff；先裁決 D1/D12 的身份與失敗生命週期，建立 red tests。不要讓各修正各自發明 cache key。
2. 修 D1、D12、D4；每項先失敗測試再實作。D12 pin/DTO 與 D8 protocol 還需 Opus 補成可直接執行的卡片，不把本文當完整實作規格。
3. 裁決並落實 D9 level1 writer、D10 lazy placements；接 D3/D6/D2/D11，確認 D7；D5 平台範圍先登錄裁決。
4. 個別測試用 `.venv\Scripts\python.exe -m pytest <file> -q --tb=short`，一次一份；GUI driver 用 `.venv\Scripts\python.exe scripts/verify_supervise.py --stall 120 --ceiling 900 -- <driver.py>`，讀到 exit code。正式全 suite 僅 `scripts/run_suite.py`，保持前景。
5. A5 commit 前補 ARCHITECTURE 的 content_scan/scan protocol、PITFALLS + index、TODOS，完成 ruff、必要 mypy、無回歸、視覺 save/reopen 與 H23 所需 review。本文不替代上述項目，也不授權 git add/commit/push。
6. A5 與 A6 分開評估；A6 完成才能移除 browse known failures、宣告全部 M0 達標，再往 Track B。

## Appendix

### A. Compression and discovery probe

將以下完整 script 存至 `$env:TEMP/cad_advice_probe.py`。命令（repo root）：

```powershell
.venv\Scripts\python.exe -c "import os; from pathlib import Path; exec(compile((Path(os.environ['TEMP']) / 'cad_advice_probe.py').read_text(), 'cad_advice_probe.py', 'exec'))" *> $env:TEMP\cad_advice_probe_output.txt
```

最後完整 run exit 0。以下原始 script / output 包含試驗性暫時替換，僅供隔離 probe；不是 production patch。所有 source 修改都只在該 Python process 內，PDF 在 temporary directory，結束關閉模型與文件。早期 probe 曾漏傳 close_session 的 session_id，修正後重跑；另一次誤 import exact_set_key，修正 import 後重跑。下列僅為最終成功版本。

```python
from __future__ import annotations
import json
import tempfile
import time
import zlib
from pathlib import Path
import fitz
from test_scripts.test_native_image_ops_stall import _build
from test_scripts.test_gui_stall import build_image_page
from model.pdf_model import PDFModel
from model import pdf_content_ops as ops
from model import pdf_object_ops
from model.object_requests import MoveObjectRequest, ResizeObjectRequest, RotateObjectRequest, DeleteObjectRequest
from utils.pdf_object_source import exact_set_key

def timed(fn):
    start = time.perf_counter()
    value = fn()
    return value, round((time.perf_counter() - start) * 1000, 3)

with tempfile.TemporaryDirectory(prefix='cad-advice-') as folder:
    path = Path(folder) / 'heavy.pdf'
    _build(path)
    print('version', fitz.VersionBind, 'fixture_bytes', path.stat().st_size)
    real_update = fitz.Document.update_stream
    def selected_update(doc, xref, data, mode):
        if mode != 'zlib1':
            return real_update(doc, xref, data, compress=mode)
        real_update(doc, xref, zlib.compress(data, level=1), compress=0)
        with exact_set_key(doc):
            doc.xref_set_key(xref, 'Filter', '/FlateDecode')
            doc.xref_set_key(xref, 'DecodeParms', 'null')
    for compress in (1, 0, 'zlib1'):
        with fitz.open(path) as doc:
            xref = doc[0].get_contents()[0]
            raw = doc.xref_stream(xref) + b'\n'
            _, ms = timed(lambda: selected_update(doc, xref, raw, compress))
            print('update', json.dumps(dict(compress=compress, ms=ms, decoded=len(raw), raw=len(doc.xref_stream_raw(xref)))))
            for garbage, deflate in ((0, False), (1, False), (1, True), (4, True)):
                saved, save_ms = timed(lambda: doc.tobytes(garbage=garbage, deflate=deflate))
                with fitz.open(stream=saved, filetype='pdf') as reopened:
                    restored = reopened.xref_stream(reopened[0].get_contents()[0])
                print('save', json.dumps(dict(compress=compress, garbage=garbage, deflate=deflate, bytes=len(saved), ms=save_ms, decoded_equal=restored == raw)))
        def update(self, xref=0, stream=None, new=1, compress=1):
            return selected_update(self, xref, stream, selected)
        selected = compress
        for name in ('move', 'resize', 'rotate', 'delete'):
            model = PDFModel()
            session_id = model.open_pdf(str(path))
            ops.discover_native_image_invocations(model.doc, 1)
            rect = fitz.Rect(320, 420, 440, 500)
            reqs = {
                'move': (pdf_object_ops.move_object, MoveObjectRequest('native_image:1:0', 'native_image', 1, 1, rect)),
                'resize': (pdf_object_ops.resize_object, ResizeObjectRequest('native_image:1:0', 'native_image', 1, rect)),
                'rotate': (pdf_object_ops.rotate_object, RotateObjectRequest('native_image:1:0', 'native_image', 1, 90)),
                'delete': (pdf_object_ops.delete_object, DeleteObjectRequest('native_image:1:0', 'native_image', 1)),
            }
            fitz.Document.update_stream = update
            try:
                fn, req = reqs[name]
                result, ms = timed(lambda: fn(model, req))
            finally:
                fitz.Document.update_stream = real_update
            print('model_edit', json.dumps(dict(compress=compress, action=name, ms=ms, result=result)))
            sizes = {}
            for deflate in (False, True):
                saved = model.doc.tobytes(garbage=1, deflate=deflate)
                sizes[str(deflate)] = len(saved)
            print('edit_save_bytes', json.dumps(dict(compress=compress, action=name, sizes=sizes)))
            model.close_session(session_id)
    images = Path(folder) / 'images.pdf'
    build_image_page(images)
    for name, source in (('images', images), ('heavy', path)):
        with fitz.open(source) as doc:
            result, cold = timed(lambda: ops.discover_native_image_invocations(doc, 1))
            _, warm = timed(lambda: ops.discover_native_image_invocations(doc, 1))
            page = doc[0]
            infos, nohash = timed(lambda: page.get_image_info(hashes=False, xrefs=False))
            print('discovery', json.dumps(dict(fixture=name, count=len(result), cold_ms=cold, warm_ms=warm, nohash_ms=nohash, info_count=len(infos))))
            real_rects = fitz.Page.get_image_rects
            fitz.Page.get_image_rects = lambda *a, **k: []
            try:
                direct, direct_ms = timed(lambda: ops.discover_native_image_invocations(doc, 1))
            finally:
                fitz.Page.get_image_rects = real_rects
            print('fixture_only_no_placements', json.dumps(dict(fixture=name, identical=direct == result, ms=direct_ms)))
```

Output (verbatim):

```text
version 1.27.1 fixture_bytes 1405888
update {"compress": 1, "ms": 610.272, "decoded": 4292826, "raw": 1402151}
save {"compress": 1, "garbage": 0, "deflate": false, "bytes": 1405890, "ms": 1.291, "decoded_equal": true}
save {"compress": 1, "garbage": 1, "deflate": false, "bytes": 1405890, "ms": 1.186, "decoded_equal": true}
save {"compress": 1, "garbage": 1, "deflate": true, "bytes": 1405492, "ms": 1.337, "decoded_equal": true}
save {"compress": 1, "garbage": 4, "deflate": true, "bytes": 1405492, "ms": 1.319, "decoded_equal": true}
model_edit {"compress": 1, "action": "move", "ms": 863.496, "result": true}
edit_save_bytes {"compress": 1, "action": "move", "sizes": {"False": 1405887, "True": 1405489}}
model_edit {"compress": 1, "action": "resize", "ms": 854.394, "result": true}
edit_save_bytes {"compress": 1, "action": "resize", "sizes": {"False": 1405887, "True": 1405489}}
model_edit {"compress": 1, "action": "rotate", "ms": 933.803, "result": true}
edit_save_bytes {"compress": 1, "action": "rotate", "sizes": {"False": 1405889, "True": 1405490}}
model_edit {"compress": 1, "action": "delete", "ms": 985.915, "result": true}
edit_save_bytes {"compress": 1, "action": "delete", "sizes": {"False": 1402818, "True": 1402818}}
update {"compress": 0, "ms": 1.377, "decoded": 4292826, "raw": 4292826}
save {"compress": 0, "garbage": 0, "deflate": false, "bytes": 4296546, "ms": 5.201, "decoded_equal": true}
save {"compress": 0, "garbage": 1, "deflate": false, "bytes": 4296546, "ms": 2.866, "decoded_equal": true}
save {"compress": 0, "garbage": 1, "deflate": true, "bytes": 1404919, "ms": 275.913, "decoded_equal": true}
save {"compress": 0, "garbage": 4, "deflate": true, "bytes": 1404919, "ms": 312.988, "decoded_equal": true}
model_edit {"compress": 0, "action": "move", "ms": 134.463, "result": true}
edit_save_bytes {"compress": 0, "action": "move", "sizes": {"False": 4296545, "True": 1404917}}
model_edit {"compress": 0, "action": "resize", "ms": 148.79, "result": true}
edit_save_bytes {"compress": 0, "action": "resize", "sizes": {"False": 4296545, "True": 1404917}}
model_edit {"compress": 0, "action": "rotate", "ms": 138.984, "result": true}
edit_save_bytes {"compress": 0, "action": "rotate", "sizes": {"False": 4296546, "True": 1404919}}
model_edit {"compress": 0, "action": "delete", "ms": 137.687, "result": true}
edit_save_bytes {"compress": 0, "action": "delete", "sizes": {"False": 4293486, "True": 1402247}}
update {"compress": "zlib1", "ms": 63.827, "decoded": 4292826, "raw": 1813477}
save {"compress": "zlib1", "garbage": 0, "deflate": false, "bytes": 1817233, "ms": 2.848, "decoded_equal": true}
save {"compress": "zlib1", "garbage": 1, "deflate": false, "bytes": 1817233, "ms": 1.481, "decoded_equal": true}
save {"compress": "zlib1", "garbage": 1, "deflate": true, "bytes": 1816835, "ms": 1.48, "decoded_equal": true}
save {"compress": "zlib1", "garbage": 4, "deflate": true, "bytes": 1816835, "ms": 1.59, "decoded_equal": true}
model_edit {"compress": "zlib1", "action": "move", "ms": 169.687, "result": true}
edit_save_bytes {"compress": "zlib1", "action": "move", "sizes": {"False": 1817232, "True": 1816834}}
model_edit {"compress": "zlib1", "action": "resize", "ms": 173.085, "result": true}
edit_save_bytes {"compress": "zlib1", "action": "resize", "sizes": {"False": 1817232, "True": 1816834}}
model_edit {"compress": "zlib1", "action": "rotate", "ms": 200.207, "result": true}
edit_save_bytes {"compress": "zlib1", "action": "rotate", "sizes": {"False": 1817236, "True": 1816838}}
model_edit {"compress": "zlib1", "action": "delete", "ms": 211.508, "result": true}
edit_save_bytes {"compress": "zlib1", "action": "delete", "sizes": {"False": 1814162, "True": 1814162}}
discovery {"fixture": "images", "count": 3, "cold_ms": 231.122, "warm_ms": 174.855, "nohash_ms": 0.194, "info_count": 3}
fixture_only_no_placements {"fixture": "images", "identical": true, "ms": 0.764}
discovery {"fixture": "heavy", "count": 1, "cold_ms": 86.993, "warm_ms": 72.137, "nohash_ms": 82.552, "info_count": 1}
fixture_only_no_placements {"fixture": "heavy", "identical": true, "ms": 4.983}
```

### B. Real capped allocation with injected find_tables allocation site

儲存為 `$env:TEMP/cad_memory_probe.py`，在獨立 Python process 執行（勿在互動產品 process 設 cap）：

```powershell
.venv\Scripts\python.exe -c "import os; from pathlib import Path; exec(compile((Path(os.environ['TEMP']) / 'cad_memory_probe.py').read_text(), 'cad_memory_probe.py', 'exec'))" *> $env:TEMP\cad_memory_probe_output.txt
```

Exit 0。script 與輸出如下；native 配置是真實拒絕，table.make_edges 的呼叫位置為刻意注入。

```python
from __future__ import annotations
import ctypes
import json
import fitz
import pymupdf.table as table
from src.object_probe import memory_limit as limit

doc = fitz.open()
page = doc.new_page()
page.insert_text((30, 30), 'real text')
cap = 128 * 1024 * 1024
limit.apply_job_memory_limit(cap)

def peak():
    info = limit._ExtendedLimits()
    returned = ctypes.c_ulong()
    ok = limit._kernel32.QueryInformationJobObject(limit._job_handle, 9, ctypes.byref(info), ctypes.sizeof(info), ctypes.byref(returned))
    return dict(ok=bool(ok), peak_commit=info.PeakProcessMemoryUsed, cap=info.ProcessMemoryLimit)

print('before', json.dumps(peak()))
def allocation(*args, **kwargs):
    return fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 10000, 10000), False)
try:
    allocation()
except Exception as exc:
    print('native', type(exc).__name__, isinstance(exc, MemoryError), str(exc))
print('after_native', json.dumps(peak()))
real = table.make_edges
table.make_edges = allocation
try:
    answer = page.find_tables()
    print('find_tables_return', repr(answer))
finally:
    table.make_edges = real
print('after_find_tables', json.dumps(peak()))
try:
    data = bytearray(300 * 1024 * 1024)
except Exception as exc:
    print('python', type(exc).__name__)
print('after_python', json.dumps(peak()))
doc.close()
```

Output (verbatim):

```text
before {"ok": true, "peak_commit": 44802048, "cap": 134217728}
native FzErrorSystem False code=2: malloc (300000000 bytes) failed
after_native {"ok": true, "peak_commit": 44802048, "cap": 134217728}
Consider using the pymupdf_layout package for a greatly improved page layout analysis.
find_tables: exception occurred: code=2: malloc (300000000 bytes) failed
find_tables_return None
after_find_tables {"ok": true, "peak_commit": 44818432, "cap": 134217728}
python MemoryError
after_python {"ok": true, "peak_commit": 44818432, "cap": 134217728}
```

### C. Cache and identity inventory

```powershell
rg -n 'id\(doc|id\(self\.doc' model controller view src utils
```

Exit 0，完整輸出：

```text
model\font_stream_compaction.py:74:# id(doc) -> nesting depth of active scopes.  Keyed by id(): a scope's exit always
model\font_stream_compaction.py:87:    return _ACTIVE_SCOPES.get(id(doc), 0) > 0
model\font_stream_compaction.py:98:    key = id(doc)
model\table_objects.py:61:        id(doc),
```

```powershell
.venv\Scripts\python.exe -c "from model import content_scan as c; from dataclasses import replace; s=c.scan_stream(b'/I Do'); a=replace(s,dos=s.dos*100001); c.store_scan(b'a',a); c.store_scan(b'b',a); print('after_store_a_b',c.cached_scan(b'a') is not None,c.cached_scan(b'b') is not None); c.store_scan(b'a',a); print('after_retry_a',c.cached_scan(b'a') is not None,c.cached_scan(b'b') is not None); c.mark_scan_failed(c.content_key(b'/I Do')); print('same_content_other_doc_failed',c.scan_failed(c.content_key(b'/I Do'))); c.clear_scan_cache()"
```

Exit 0，完整輸出：

```text
after_store_a_b False True
after_retry_a True False
same_content_other_doc_failed True
```

這個最小測試重複同一 immutable record 以隔離 cache 計數政策，不宣稱這是有效 100001-Do 內容的完整 StreamScan；實作時另用合法 streams 做 integration test。

### D. Verification and fence record

- 獨立 `plan-code-reviewer` 最終 verdict：`ship`，僅指 advisory 可交 Opus；18 項 brief 要求均 Honoured，無未處理的 confirmed findings。審閱已修正 Appendix 編碼、D9 `/Length` 說法、D2 baseline 與 red-first 的區分。
- `.venv\Scripts\python.exe -m ruff check .` → exit 0，`All checks passed!`；文件檢查 → exit 0，12 個 D sections、15 行 header、無 device patterns、無亂碼、code fences 成對。檢查只證明文件與 lint，不代表 proposed product changes 已測試。
- 本輪沒有修改 production，也沒有新增或跑正式 pytest／GUI driver；所有「Red first」是交給 Opus 實作前的要求，未冒稱已通過。
- 沒有執行 whole-suite、mypy、save/reopen 視覺檢查、跨平台 runtime、H23 全段 review；本輪目的為 advisory，相關產品 gate 仍未完成。
- repo 只新增本 advice；scratch probe 與輸出在 TEMP，未 commit、stash、reset 或清理既有修改。
- `git status --short` / `git diff` 有 global Git ignore 讀取權限 warning，但命令仍 exit 0；未改環境或權限繞過。
- Fence log：alias 成長（N4）僅登錄；未刪未使用 helper、未擴張全域 save policy、未開跨平台實作。
- Verified：反證「session UUID 足以防 reuse」→ snapshot restore 換 handle，需獨立世代；反證「peak 可識別 cap OOM」→ rejected 大 allocation 時 peak 僅約 33%；反證「D10 必須新 child」→ 指定 direct fixtures 的完整 invocation 不需要 placements；反證「raw 最佳」→ level1 提供 170–212 ms 模型編輯與較小檔案；反證「oversized alone 解完 readiness」→ 兩份 scan 輪流 eviction。實際 GUI、fallback parity、完整 undo/filter 回歸仍是待驗 gate。
