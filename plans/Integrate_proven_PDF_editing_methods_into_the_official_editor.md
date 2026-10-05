# 將已驗證的 PDF 編輯方法接入正式編輯器

## 1. 目標與已確定的範圍

第一階段以這 10 個成功樣本為驗收基準，讓使用者透過正常介面完成「選取 → 輸入 → 預覽 → 套用 → 復原／重做 → 存檔重開」，外觀與實驗成果一致。

採用你選定的策略：

- 先支援原嵌入字型已有的字元，不在本階段加入缺字補嵌入。
- 無法保真時保留原文與尚未套用的輸入，提供明確的「重建文字」替代操作。
- 不自動退回舊式刪除重插，不將拒絕編輯計算為成功。
- 延用現有 Tier 0／Tier 1 架構；實驗腳本保留作獨立對照，不直接搬進正式程式繞過驗證。

## 2. 修改文字引擎：修正三個實際阻塞點

### A. 修正預覽副本被誤判為文件變更

**主要修改：`model/text_commit/inspect.py`，配合 `engine.py`、`preview.py` 的測試。**

已確認第 5～7 頁的原檔與副本，透明度值由 `float:1` 正規化為 `int:1`，使 ExtGState 指紋不同；文字、字型與頁面幾何並沒有改變。

修改方式：

- 將指紋中的 PDF 數值改為語意一致的表示，使 `1`、`1.0` 相同；字典鍵順序不影響結果。
- 不增加浮點容差、不用小數截斷掩蓋差異。`1` 與 `0.999999`、不同字型、字寬、透明度及內容串流仍必須產生不同指紋。
- 保留 live document、preview scratch、commit 三處的 stale 檢查；不能藉重新指定指紋或略過檢查來讓測試通過。

### B. 修正圖層標記與圖形狀態堆疊的混淆

**主要修改：`model/text_commit/replay.py`、`marked_content.py`。**

第 5 頁的 `BDC/EMC`、`q/Q`、`BT/ET` 各自平衡，目標也是預設可見的 `/OC` 圖層，目前卻因跨越 `q/Q` 被分類為 malformed。

修改方式：

- 分別追蹤各組操作的配對；`Q` 不結束或破壞 marked-content stack。
- `crossed_q` 不再單獨代表標記損壞；保留作診斷資訊即可。
- 仍拒絕未閉合、堆疊下溢、無法解析或不可見圖層，以及替換範圍跨出所屬 wrapper 的情況。
- 不移動、刪除或重排原有 `BDC/EMC`、`q/Q` 操作。此方向符合規範對各組操作「分別配對」的要求。[PDF 規範勘誤](https://pdf-issues.pdfa.org/32000-2-2020/clause14.html)

### C. 支援本次已驗證的鏡射文字

**主要修改：`model/text_commit/transforms.py`、`plan.py`、`verify.py`。**

修改方式：

- 將「鏡射」與「退化矩陣」分開判斷，保留原矩陣的方向與正負號。
- 第一階段新增支援限定為：填色文字、正交等向矩陣、視覺基線為水平或垂直、替換前後 advance 相同的原資源修改。
- 四個角都經完整矩陣轉換，再計算文字邊界；不能假設文字永遠向右延伸。
- 剪切、奇異矩陣、尚未證明的鏡射寬度變更仍拒絕，不全面開放任意變換。

### D. 接通既有字碼替換與寬度補償

**沿用並補測：`cid_fonts.py`、`plan.py`、`patch.py`。**

- 等 advance：只替換原字串 operand。
- 不等 advance：使用既有 Tier 1 的 `[<CID> K] TJ`，保留後續文字起點；本次 `Drawing List → Drawing Title` 的補償為 `+333`，`A版 → B版` 為 `−79`。
- 保留原字型資源、`Tf/Tm/CTM/Tz/Tc/Tw/Ts/Tr`，不使用 `span.size` 重建文字。
- 繼續檢查 CID 唯一性、嵌入字形存在、字寬可證明及擴張區域沒有其他內容。
- 成功路徑禁止呼叫 redaction、HTML 插字或系統字型替換。

## 3. 修改介面與資料流：預覽和套用必須是同一個結果

**主要修改：`view/text_editing.py`、`view/pdf_view.py`、`controller/pdf_controller.py`，配合現有 preview coordinator。**

### 選取與預覽

- 預設選取改為「詞／Run」，段落模式保留供明確選擇，避免圖面表格跨欄、跨列被組成編輯目標。
- 以原文字、來源識別與座標共同定位；重複的 `Buffer Tank` 必須分得開，不能只取第一筆相同文字。
- 純文字修改不得產生字型或字級 override；只有使用者真的操作格式控制項才建立 override。
- 預設啟用 plan preview，沿用現有 150 ms debounce、QThread、session／generation 與快取。
- 停止把 CSS 重建影像作為穩定模式的輸入預覽。等待期間保留原圖或上一張已驗證影像，明示「預覽更新中」，保留使用者輸入。
- 只有目前 generation 的驗證影像與 `plan_token` 同時存在時，才允許正常套用。過期結果、換頁、切換文件及新輸入都使舊 token 失效。

### 套用與明確替代操作

**接口調整：`EditTextRequest` 新增 `allow_rebuild: bool = False`；延用既有 `PreparedEdit`、`CommitOutcome` 及 `confirm_fallback`。**

- 正常「套用」提交畫面已顯示的同一個 `PreparedEdit`。token 過期或候選失效時重新預覽，不默默改用另一種寫入方式。
- 預覽拒絕時顯示易懂原因，例如「原字型沒有這個字」，並提供「改用重建文字…」。
- 只有該按鈕能設定 `allow_rebuild=True`，再透過既有確認介面說明可能改變字型與排版；預設選項為保留編輯。
- `model/pdf_text_edit.py` 在沒有明確同意時不得進入 legacy fallback；缺少 callback 也不代表同意。
- 確認只適用本次內容與目標。修改輸入後必須重新判定；重做則重放已確認的結果。
- 修正 finalize 流程：以真正的提交結果判定成功，而不是以 signal 發送成功判定。取消、拒絕及失敗都保留輸入，不關閉編輯器、不顯示成功通知。

正式預設採 `engine='tiered'`、`max_tier=1`、`preview='plan'`；允許經明確選擇的重建，但取消自動降級。既有診斷環境變數保留，不作正常使用的必要設定。

## 4. 復原、存檔與驗收

**主要涉及：`model/edit_commands.py`、`model/pdf_model.py`。**

- 穩定編輯沿用原串流 patch 的反向／正向重放，復原與重做不能重新走刪除重插。
- 延用 `fidelity_protected_pages`，確保背景整理及存檔前處理不對這些頁執行 `clean_contents()`。
- 不把實驗的 `saveIncr()` 硬套到所有存檔情境；保留現有加密、另存及安全清除政策。
- 存檔重開後比較文字、字型資源內容、幾何與影像。完整存檔可能重編 xref，不能只以物件編號判定失敗；需要同步清除失效的預覽快取。

### 必須通過的測試

| 層級 | 驗收內容 |
|---|---|
| 引擎 | 10 個樣本經正式 prepare／commit 全部成功，結果皆為原字型資源重用，不能是 degraded commit |
| 指紋 | `1`／`1.0` round-trip 不誤報；真正修改透明度、字型、字寬或串流仍判 stale |
| 標記與矩陣 | 合法的独立配對及指定鏡射通過；未閉合、下溢、隱藏圖層、奇異矩陣仍拒絕 |
| 外觀 | 與本次實驗結果比較；逐處 6 倍裁切目視一致，目標區域外 2 倍渲染像素差異為 0 |
| UI | 10 筆經正常選取與鍵盤輸入完成；快速輸入、中文組字、過期預覽及重複文字不提交錯誤目標 |
| 失敗處理 | 缺字、拒絕或取消替代操作時，PDF 不變、輸入保留、沒有成功通知 |
| 完整流程 | 每筆復原還原原圖、重做還原修改圖；另加同頁連續修改，再存檔重開驗證 |

真實 HVAC fixture 是本機必跑驗收；另建立不含原文件內容的最小合成案例供 CI 執行。不能以 fixture 缺席造成的 skip 宣稱完成。

## 5. 實作順序與完成條件

1. 先把 10 筆案例接到正式流程，建立會失敗的驗收測試。
2. 依序修正指紋、標記配對、鏡射與 Tier 1 路徑，每一步保留反例測試。
3. 接通預覽、token、正常套用與明確重建操作，再調整預設值。
4. 完成 UI 操作、復原／重做及存檔重開驗收，更新實驗報告與專案文件。
5. 執行相關測試、全樹 ruff、型別與架構檢查，最後跑一次完整回歸套件。

**完成標準是這 10 筆在正式介面全部達到實驗品質，且拒絕時不再偷偷換字型。** 缺字嵌入、跨多個 run 的段落重排、任意變換與 Form XObject 擴充留待下一階段。

## 6. 執行紀錄（2026-09-29 起，分支 `feat/true-text-edge-cases`）

### 基線（修改前，venv PyMuPDF 1.27）

`test_text_commit_real_corpus_acceptance.py::test_production_engine_prepares_all_fourteen_real_type0_edits`
紅燈：14/14 拒絕 — `mc_malformed_pairing` 8、`verification_failed` 5、`trm_reflected` 1。

### 已證實的根因

- **A（指紋）已證實，唯一差異元件是 ExtGState。** 對 HVAC 第 5／6／7 頁與 ECC 第 1 頁逐元件比對
  live 與 scratch 的 `page_fingerprint`：streams、字型、marked content、幾何、annots 全部相同；只有
  `_update_extgstate_dependencies` 經 `_canonical_object_digest` 得到 `CA\x1ffloat\x1f1` 與
  `CA\x1fint\x1f1` 的差異（值字串同為 `1`，只有 kind 從 float 變 int）。第 5 頁同樣受影響，
  所以 B／C 修好後，那 9 筆預期會轉為 `verification_failed`，不會直接通過。
- B／C 尚待定位：`replay.py` 在 `Q` 使 depth 低於 open depth，或 EMC depth 不等時設 `crossed_q`；
  `marked_content.classify_wrapper` 將 `crossed_q` 視同 malformed。`transforms.shape_reject_reason`
  將所有 det<0 一律拒絕。
- **2026-09-29 A 已落地（決定）。** 單一 chokepoint `cid_fonts.canonical_pdf_scalar(kind, value)`：
  `int`/`float` 一律折成 `("num", 精確十進位文字)`（`Decimal(str)` + `format(..., "f")` 去尾零，
  `-0`→`0`；刻意不用 `Decimal.normalize()`，它會依 context 精度 28 位捨入）；非數值 kind 或讀不成有限數
  的文字原樣回傳（fail-closed）。套用三處：`inspect._canonical_object_digest` keyed 分支、
  `inspect._fold_canonical_value` scalar 分支、`marked_content._fold_target_structured`。
  合成文件即可重現（`update_object(x, "<< /CA 1.0 >>")` 未存檔：live `float:1`、scratch `int:1`）。
  驗收：14 筆中 5 筆 `verification_failed` 全部轉為 PREPARED（hvac p6/show60 T0、p6/show58 T1、
  p7/show7 T0、ecc p1/show57 T0、p1/show60 T1）；剩 9 筆 = `mc_malformed_pairing` 8、`trm_reflected` 1。
- **2026-09-29 A 刻意不改（證據）。** 兩個 raw `xref_object` fallback（`_canonical_object_digest`
  的 array/scalar 分支、`_fold_target_structured` 無 key 分支）：序列化只印值不印 kind，實測
  `[500 250.0 1.0 0.5 -0.0]` 兩側皆為 `[ 500 250 1 .5 0 ]`。`/UserUnit` 已是 `num:float` 折法。
  `fonts.py` 與 `compute_cid_evidence_digest` 的 `kind:value` 是同文件 registry key，不跨 scratch。
  `canonical_pdf_text` 的 float 以 `:.6f` 格式化（`0.9999999` 與 `1` 同值）屬另一類捨入風險，
  共用於 evidence/registry digest，本步未改，列為待辦。
- **2026-09-29 B 已落地（決定）。** 實測骨架（只記運算子／深度）：hvac p5 wrapper 與 ecc p1 wrapper
  皆為 `q BDC … Q q … <target> … EMC Q`，同一 stream 內閉合、EMC 回到開啟時的 gs depth 1，只有
  「Q 使 depth 低於 open depth」這個觸發條件成立；目標 show 位於 `[open_op_end, close_op_start]` 內。
  replay 的 `mc_open` 本來就與 gs stack 分開（Q 不會關閉或破壞 MC stack），所以只改 chokepoint
  `marked_content.classify_wrapper`：只有 `not closed` 算 `malformed_pairing`，`crossed_q` 保留為診斷欄位；
  拒絕訊息改為 `wrapper is unclosed`。census／funnel／painter 腳本都走 `classify_wrapper`／
  `admit_show_wrappers`，一併一致；`replay_index_spike.py` 只重算診斷欄位，不動。
  仍拒絕：未閉合、EMC 下溢、props 無法解析、隱藏 OCG、OCMD、跨 stream wrapper（`splice_range_within_wrapper`
  既有的 containment gate）。稽核：Tier 0 只換 string operand／單一 TJ item，Tier 1 只換 `[op_start, op_end)`
  整個 show 運算子，`build_advance_preserving_erase` 在 model／controller 無呼叫者；沒有路徑插入或移動
  q/Q/BDC/EMC，故不需為特定路徑保留 crossing 拒絕。兩個舊 pin（mc_admission 的
  `test_wrapper_crossing_q_is_rejected`、census 的 `test_crossing_wrapper_is_malformed_pairing`）依 §2.B
  翻轉並改名，同時斷言 `crossed_q` 仍為 True。驗收：8 筆 `mc_malformed_pairing` 中 7 筆轉為 PREPARED
  （ecc commit／reopen 測試轉綠）；hvac p5/show26（Tier 1 補償 +333）改停在 `growth_region_not_blank`
  （vector drawing 與 growth zone 相交），另案追查；剩 `trm_reflected` 1 筆屬 C。
- **2026-09-29 C Step 0（實測，hvac p7/show5）。** Tm `(-0.06, 0, 0, 0.06)`、CTM ≈ `(1+2e-9)` 等向、
  Tz 100、Tc/Tw/Ts 0、Tr 0、Tf 62.73；TRM `(-0.06, 0, 0, 0.06)`，det −0.0036，兩列範數相等、正交。
  頁面 /Rotate 270，visual frame `(0, -1, -1, 0, 1191, 842)`。鏡射在**基線軸**（a<0、d>0）：
  基線 (1,0) → visual (0, +0.06)＝向下延伸；升部 (0,1) → visual (−0.06, 0)＝向左。
  對照 show7（同字串、未鏡射）基線向上、升部向左；show7 `trm_uniform_scaled=True` 不進相對 gate，
  show5 為 False，進入 gate。
- **2026-09-29 C 已落地（決定）。** `transforms.shape_reject_reason(allow_reflection=True)` 只跳過方向性
  gate；singular 本就用 `|det|`，正交（a·c+b·d）與等範數與方向無關，故剪切／非等向鏡射仍拿自己的碼、
  同一組相對邊界。`admission_verdict(render_mode=...)`：det<0 時，僅在 `render_mode == 0`（呼叫端證明）、
  orientation-blind 形狀通過、視覺基線 cardinal 三者皆成立才回 `reflected=True`；`render_mode=None`
  （未提供）維持 `trm_reflected`，所以沒更新的呼叫端 fail-closed。被拒的鏡射一律保持 `trm_reflected`
  （既有優先序 orientation 先於 shear／norm／direction，census slug 對應不變）。
  `inspect.trm_bind_rejection` 與 `plan._classify_common` 傳 `show.render_mode`；`_ClassifiedTarget.trm_reflected`
  驅動：(1) 鏡射且 advance 非精確可證（simple font 無 `/Widths`、`advance_source == "face"`）→ `trm_reflected`；
  (2) `_build_tier0` 在 ADVANCE_MISMATCH 之前檢查，鏡射且 advance 變動 → 新碼
  `trm_reflected_advance_change`（不升級 Tier 1）；(3) `_build_tier1` 首階 fence 同碼。Tm/cm 位元組不改寫：
  Tier 0 只換字串 operand。`scripts/measure_type0_funnel.py` 兩處 `admission_verdict` 補 `render_mode`，
  與 binder 一致；census（`trm_taxonomy`）走預設 shape gate，不變；audit 走 `trm_bind_rejection`，自動一致。
- **2026-09-29 C 幾何稽核（結論）。** fallback `target_bbox`、painter core／reach（`_painter_reach` 只看
  `det != 0`）、glyph ink（`predict_glyphs` 用帶號 `(a, b)`、`map_text_quad_to_visual` 四角映射）
  全部與正負號無關；唯一依方向的是 Tier 1 的 `_grown_verify_bbox` 與 verify `_growth_zone_rect`，
  已由 Tier 1 fence 隔開。V0c 抽字、V0d 光柵對鏡射 CJK／Latin 皆通過（合成＋實檔）。
- **2026-09-29 C 翻轉的舊 pin。** `test_reflected_tm_is_rejected`（`1 0 0 -1`）與
  `test_quarter_turn_mirror_is_rejected_as_reflected_not_rotation`（`0 1 1 0`）依 §2.C 改為正例
  （cross-axis／quarter-turn），併入 `test_mirrored_tm_with_equal_advance_admits_and_commits_tier0`。
  transforms 層 `admission_verdict` 的 mirror pin 未傳 render_mode，維持 `trm_reflected` 不動；
  `structural_gates::test_planner_rejects_mirror_text_matrix`（Helvetica face-derived）維持 `trm_reflected`。
- **2026-09-29 C 驗收。** 14 筆中 13 筆 PREPARED（p7/show5 → Tier 0，方向 down）；剩
  hvac p5/show26 `growth_region_not_blank`（B 已記錄，另案）。p7/show5 在暫存副本上 prepare→commit→
  saveIncr→reopen：stream 為精確 splice、Tm/CTM 等文字狀態不變、首字 origin 相同、texttrace
  font/dir/size/color 相同、show7 與其他 show 未移動、差異像素 206 全在 mask 內。
  **下一個阻塞（非 C 引起）：** 排除 show26 跑 hvac commit/reopen 測試，`_assert_only_target_streams_changed`
  在 reopen 後報「非目標 xref（被編輯頁的 page 物件）changed」：live 物件與原檔相同，`saveIncr` 後
  重開的序列化只有 inline dict 的 `/Type`／`/Subtype` 鍵序不同；不含 show5 時在 p5 page xref 27 同樣
  重現，故與 C 無關；成因未確定（本分支 commit 路徑、測試 harness、PyMuPDF `saveIncr` 皆可能——
  此測試在 A／B 之前從未走過 prepare）。未處理、未放寬斷言；排在 p5/show26 之後的 hvac commit 阻塞。
- **2026-09-29 VERIFY（獨立驗證，未改產品碼／測試）。** 驗收 13/14 PREPARED、ecc commit/reopen PASS、
  hvac 兩測試只因 p5/show26 `growth_region_not_blank` 失敗；text_commit 全套、census、ruff、mypy 皆綠。
  show26 成因：`verify._drawings_intersect_growth` 比對 path bbox，p5 的頁框（開放、僅描邊、3 段 `l`）
  bbox 幾近整頁，逐段檢查並無交集——需新的幾何證明，不可放寬；raster 背景證明能否通過未知。
  前述 page xref 改鍵序的成因已定位：測試 `_prepare` 內 `_trace_for` 對 candidate 呼叫
  `get_texttrace()` 即使頁 dict 變髒（僅 `/Type` 移前，鍵值全同）；另 hvac 的 live render 與 reopen
  不同只在 image xref 649 的放置區（live 端先做 `get_text` 後的影像快取差異），reopen 對原檔的差異全在
  edit mask 內。兩者都需改既有驗收斷言，交由擁有者決定。

### 第二輪（14 筆轉綠後）

1941 批的 5 個候選不在 14 筆驗收內；`cand-hvac-kai-cover` 的 `mc_wrapper_not_pure_layer`
（`struct_content`）屬 T16-4X S2 範圍（尚未落地），列為第二輪，不在第一輪放寬。

### 2026-09-29 A/B/C 結果（workflow wf_538f2d1f-bba，獨立驗證）

- 14 筆 prepare：13 通過（Tier 0 11、Tier 1 2），1 拒絕：hvac p5/show26 `Drawing List→Drawing Title`
  `growth_region_not_blank`。原因是 `verify._drawings_intersect_growth` 以 path bbox 判斷，第 5 頁圖框（開放、
  只描邊、3 段 `l`，bbox 幾乎整頁）被當成覆蓋成長區；逐段描邊幾何則沒有交集。
- ECC commit/reopen 綠燈；HVAC commit/reopen 還卡在兩個 harness 現象（尚未判定歸屬）：
  `get_texttrace()` 讓頁面字典重新序列化（`/Type` 移到最前）；live 文件做 `get_text('rawdict')` 後，
  image xref 649 在同一 session 的渲染與重開不同。
- 全 text_commit 測試、ruff、mypy 綠燈。

### 交接文件補充的驗收要求（2026-09-22 export／實驗報告）

- 目標外像素差異需 MuPDF **與 Poppler** 皆為 0。
- 保持 run-level：case 10 要讓 run 索引對應單一 show，不改為段落或多 run 取代。
- 產品存檔不強制 `saveIncr()`；存檔重開以語意比對，不比 xref 編號或原始排列。
- 負例：`空調冰水管路系統圖(1)`（缺「路」）必須 `type0_unicode_unmapped`；需保留成長空間判斷
  （較長的 ECC 圖號太靠近欄線）。

### 2026-09-29 D：成長區 occupancy 的精確描邊證明（hvac p5/show26）

- **實測（決定依據）。** show26 成長區（visual）`(238.37, 137.42)-(240.48, 143.76)`；唯一 bbox 相交的是 drawing 77
  （`type 's'`、無 fill、3 段 `l`、開放、實線）。自訂 MuPDF stroke device 量到真實狀態：CTM
  `(0, -0.06, -0.06, 0, 1174.74, 834.62)`（相似變換，scale 0.06）、linewidth 6（頁面空間半寬 0.18）、
  round join、miter limit 10、round caps、無 dash；三段線距成長區數百 pt。
- **決定：不用 `get_drawings()` 回報的 width。** PyMuPDF `width = pathfactor * linewidth`，`pathfactor` 只在
  `|a|==|d|`（或 `|b|==|c|`）時為 `|a|`（`|b|`），其餘為 1，且看不到 shear；`lineJoin` 也被乘上 pathfactor，
  miter limit 不回報。故改以 `fitz.mupdf.FzDevice2` 子類（只覆寫 `stroke_path`，自寫 `FzPathWalker2`，不實作
  rectto/quadto 讓 MuPDF 拆解）取得 CTM、linewidth、linejoin、miterlimit、caps、dash_len。新模組
  `model/text_commit/stroke_occupancy.py`；`verify._drawings_intersect_growth` 只在 bbox 已相交時才呼叫它。
- **決定：證明規則（只能更嚴，不能放寬）。** 豁免條件同時成立才回「不相交」：(1) 所有 bbox 相交的 drawing 皆
  `type 's'`、`fill is None`、`dashes == "[] 0"`、items 僅 `l`/`re`；(2) device 完整跑完，所有 path bbox（含
  控制點，外擴 1pt）碰到成長區的 stroke record 皆可精確建模且清空：CTM 為相似變換（相對容差 1e-6，半寬用
  σmax）、linewidth > 0、join ∈ {miter, round, bevel}、caps ∈ {butt, round, square}、無 curve、無 dash；每段
  capsule 半徑 `hw·√2 + margin`（涵蓋三種 cap 與零長度點）；join 圓盤 round/bevel 取 `hw`，miter 取
  `hw·max(1, min(ML, 1/sin(θ/2)))`（鄰段零長度時取 `hw·max(1, ML)`）；closed subpath 補閉合段與每個頂點的 join；
  (3) 每個相交 drawing 的頂點（dict 空間經 `quarter_turn` 轉 visual）與某個 relevant record 雙向吻合（1e-3），
  確保兩邊座標系一致。任何一項不成立 → 維持原 bbox 判定（refuse）。`S`/`s` 從不填色（ISO 32000-1 8.5.3.1），
  故封閉描邊路徑內部不是墨跡、沒有 fill rule 問題。`f`/`B`/`b`（`fs`）、`qu`、curve、dash、hairline、非等向／
  shear CTM 一律保留 bbox 拒絕。
- **決定：margin。** 原 bbox 測試沒有 margin（`_rects_overlap` 的 1e-3 只是放寬重疊判斷）。新常數
  `verify._STROKE_CLEARANCE_MARGIN_PT = _HALO_MARGIN_PT`（2pt ＞ 96 dpi 下 2.6 px，涵蓋 AA 與 MuPDF 細線加寬到 1px）。
- **raster 背景證明照跑、獨立通過。** show26 以 `page=None, doc=None` 單跑 `_growth_probe_failure`（純 raster）→
  `None`；完整證明 → `None`。未跳過、未放寬。
- **驗收。** show26 → PREPARED，Tier 1（`TIER1_REBUILD_WITH_VALIDATED_FACE`、`whole_operator`、方向 right），寫入
  `[<002700550044005A004C0051004A00030037004C0057004F0048> 333.000000] TJ`，K = +333（與獨立量測一致）；
  in-memory commit COMMITTED。`test_production_engine_prepares_all_fourteen_real_type0_edits` 14/14 綠；ecc
  commit/reopen 綠；hvac commit/reopen 現在越過 live 比對，只在 reopen 後卡既有的 page xref 27 鍵序現象（見上方
  VERIFY 記錄），未改斷言。
- **新發現（證據，未處理）。** 實測 `page.get_drawings()` 本身（`get_cdrawings` 內 `set_rotation(0)` 再還原）
  也會讓 /Rotate 頁的 page dict 在 `saveIncr` 後重新序列化（p5 page dict 前後不同）；`get_texttrace()` 同樣；
  新的 stroke device（`fz_run_page`）不會。也就是 occupancy gate 在 prepare 時就可能弄髒被編輯頁的 page 物件，
  xref 27 鍵序問題不只是測試 harness。交由擁有者決定。
- **死路。** 以 get_drawings 的 `width/2` 做 capsule（任務原始建議）：對非等向或 shear CTM 會低估墨跡，fail-open，
  放棄。以 entry↔record 逐一配對取代全域 relevant 檢查：配對失誤時可能漏測真正的 record，改為「所有 relevant
  record 都要清空」＋頂點雙向吻合作交叉檢查。
- **補測。** `test_text_commit_growth_background_box.py` Task D 區塊（開放頁框 0/90/180/270 admit＋commit 只改目標 show、
  穿越段 refuse、`f`/`B`/`b` refuse、封閉五邊形與 `re` admit、粗線半寬入侵 refuse 與細線對照 admit、miter 尖角
  refuse 與 round/bevel/ML 2 admit、curve/dash/hairline/非等向/shear/`qu` 保留 bbox 拒絕；fail-closed 釘：device 回 None → 維持 occupancy 拒絕、record 平移 50pt → 頂點交叉檢查拒絕；頁框旁另一條 bbox 不相交但 16pt 墨跡入侵的粗線 → 由 raster 拒絕，實測證明 bbox gate 忽略線寬是既有缺口、非本步引入）；
  `test_text_commit_mc_admission.py::test_tier1_whole_operator_transplant_inside_a_q_crossing_wrapper_commits`
  （B 已落地，首次執行即綠，屬覆蓋補強而非紅燈）。

### 2026-09-29 E：驗收 harness 的量測副作用（hvac commit/reopen）

- **歸屬（證據，probe 腳本包 `fitz.Page.set_rotation` 計數＋逐項 saveIncr／重開，未改產品碼）。**
  (1) page dict 鍵序（xref 27／38／51，三頁皆 /Rotate 270）：PyMuPDF 的 `get_texttrace`／`get_textpage`
  （所有 `get_text`）／`get_cdrawings`（`get_drawings`）在非 0 旋轉頁會 `set_rotation(0)` 再還原，page 物件被標髒，
  `saveIncr` 以不同鍵序重寫；live `xref_object` 不變。來源有**兩個**：測試 `_prepare → _trace_for`（候選文件上
  `get_texttrace`），以及**產品 commit**——live 驗證（`verify._span_origins` 40 次／commit 批、
  `_verify_patch_postconditions`、`count_growth_zone_glyphs`、`_images_intersect_growth`、`_drawings_intersect_growth`）
  在 live 頁上觸發 set_rotation。只 prepare（證明在 scratch）不髒；產品 prepare+commit（traces 由原檔另算、
  測試完全不碰候選）→ 三頁全髒。App 內 `PDFModel.ensure_page_index_built`（文字編輯前必呼叫）單獨就對三頁
  set_rotation 18 次、三頁全髒——text_commit 單方面修不掉。`doc.save(garbage=0)` 完整存檔後 page 物件與未碰文件的同法存檔
  相同（`_full_save_to_path`／`_atomic_full_save` garbage=4 未量）；只有增量存檔多寫一份鍵序不同、鍵值全同的
  /Page，產品上即 `save_as` 的增量分支（`use_incremental_save`、非 secure save、存回原檔）。
  (2) live render ≠ reopen（image xref 649 放置區，8180 px、最大通道差 103）：來源**只有產品 commit**。
  預設旗標的 `get_text('rawdict'/'dict')`（含 TEXT_PRESERVE_IMAGES）、`PageInterpretation.rawdict()`、
  `get_image_rects()` 都會以全解析度解碼影像進 MuPDF store，之後同一 live 文件的 render 重用它（fresh open 走 subsample
  解碼）；`get_texttrace`、`get_drawings`、`get_image_info()`、`rawdict(flags=0)`、display-list textpage、旋轉切換都不會。
  測試端沒有這類呼叫。`TOOLS.store_shrink(100)` 可消除（全域）。背景 render（`page_render_coordinator`）從 snapshot
  bytes 開新文件 → 不受影響；同步路徑 `model.get_page_pixmap`（`_render_page_into_scene` 等）直接 render live → 可觸及（未證明 commit 後實際走到這條路徑，故只算「可觸及」，非已證實使用者可見）。
- **決定：只修測試端，斷言一字未改。** `_prepare` 的 `_trace_for` 改在 `_measurement_copy(doc)`
  （`fitz.open("pdf", doc.tobytes(encryption=KEEP))`，每 case 取當下狀態，後續 case 看得到先前的編輯）；
  probe 驗證 14 筆 copy 與 live 的 trace chars／bbox 全等。像素 mask 區塊與 live==reopen 比較抽成
  `_assert_pixels_changed_only_inside_masks`／`_assert_reopened_renders_match_live`，邏輯逐行不變。
- **紅燈→綠燈。** 新增 `test_harness_prepare_measurement_does_not_mutate_the_judged_document`（hvac p5 只 prepare→
  saveIncr→重開，以既有 `_assert_only_target_streams_changed(..., set())` 判）：修前 `non-target xref 27 changed`，修後綠。
- **Mutation 守門（永久測試；單跑：物件檢查 5.6–8.8 s、兩個像素測試各 0.05 s，接在 hvac 測試之後因 GC 會到 ~14 s）。** `test_non_target_object_check_catches_deliberate_mutations`：control 綠；
  未編輯頁 content stream 一個 byte（空白→換行）、未編輯頁 /Rotate 值、被編輯 ArialMT CIDFont 的 /W 一個寬度值，
  三者皆以 `non-target xref <該 xref> changed` 失敗。`test_pixel_mask_check_catches_a_change_outside_the_mask`
  （mask 外 2pt 方塊 → `pixels changed outside target masks`；mask 內無變化也失敗）；
  `test_live_render_check_catches_a_rect_drawn_on_the_live_document`。後三者合成，但模組層 `needs_fixtures` 讓 CI 跳過。
- **驗收（修後、不加 -x）。** 10 項中 9 過：prepare 14/14、ecc commit/reopen、新增 harness／mutation 測試皆綠；
  hvac commit/reopen 仍在**重開後**的 `non-target xref 27 changed` 失敗（live 端同一檢查通過），此時已是純產品
  commit 的 set_rotation 所致；line「live==reopen render」在其後、尚未執行到，依 (2) 預期會因 image 649 失敗。
- **待擁有者決定（未處理）。** (a) 重開後的非目標比對要不要改為語意比對（本計畫「交接文件補充」已寫「存檔重開以
  語意比對，不比 xref 編號或原始排列」）——本步禁止改斷言；(b) 產品 live 驗證是否該避免 image 解碼
  （text-only 呼叫改 `flags=TEXTFLAGS_RAWDICT & ~TEXT_PRESERVE_IMAGES` 只能修一部分，`interpretation.rawdict()` 與
  `get_image_rects()` 另需處理；或 commit 後 `store_shrink`，全域副作用）。
- **新發現（pitfall 候選）。** /Rotate 繼承自 /Pages 的頁：任一 `get_text` 就把 `/Rotate` 直接寫進 page dict
  （live `xref_get_keys` 即多一鍵，不只鍵序），手工 PDF 實測。

### 2026-09-29 VERIFY D/E（獨立驗證，未改產品碼／測試）

- **驗收（不加 -x）。** 10 項 9 過，唯一失敗 `commits_reopens…[hvac]`：重開後 `non-target xref 27 changed`
  （與 E 記錄一致）；其後的 live==reopen render 斷言仍未執行到。14 筆 prepare 全過：Tier 0 11、Tier 1 3
  （hvac p5/show26、p6/show58、ecc p1/show60）。K 實寫值 `333.000000`／`-79.000000`／`-500.000000`；自寫 /W 解析
  （不經產品 registry）算 Σw(new)−Σw(old)＝+333、−79、−500（Tc=Tw=0），三者相符。
- **全套。** `not needs_fixtures` 分三批：533＋1600＋1911 passed、21 skipped、5 xfailed，0 失敗（stderr 的
  `Windows fatal exception 0x80040155` 來自 `test_win_print_fixes.py` 的 COM，已處理的 SEH，非失敗）；
  `needs_fixtures` 35 passed、1 failed（同上 hvac）。ruff 全綠、mypy 無錯。
- **E 的 harness 改動（證據）。** 兩個抽出的 helper 與原行為逐行相同；`_measurement_copy` 只改量測來源，
  不影響任何判定斷言。E 的四個 mutation 與兩個像素 mutation 測試重跑皆綠（即每個 mutation 仍被抓到）。
- **D 的 occupancy 證明：反例（證據，未處理）。** `relevant` 以 path 控制點範圍 ±1pt 篩選，**未計入**描邊半寬、
  cap、miter 伸出量。合成頁（開放頁框＋另一條 path bbox 不碰成長區的描邊）三例，`_drawings_intersect_growth`
  皆回 False，但 96 dpi 成長區內確有墨跡：20pt 粗線中心距 6pt（36 px）、2pt 線 10 M 的尖 miter 頂點距 4pt（11 px）、
  12pt 方形 cap 端點距 3pt（70 px）。無頁框時同樣 False（既有 bbox 忽略線寬的缺口）；**有頁框時 D 之前會因頁框
  bbox 拒絕、D 之後放行**，端到端只剩 raster 證明擋住（D 已用 16pt 粗線釘住 raster 拒絕）。可行收緊：relevance 改用
  每筆 record 的墨跡外擴（`hw_max·max(√2, ML) + margin`，σmax 對任意 CTM 皆可算），不需放寬任何東西。
- **D 的 mutation 缺口（證據）。** 以 in-memory 猴補重跑 `test_text_commit_growth_background_box.py`：忽略 miter、
  σ 恆為 1、關掉頂點交叉檢查、允許 fill、忽略 dash 皆被抓到；**`_STROKE_CLEARANCE_MARGIN_PT = 0` 與膠囊半徑去掉 √2
  （方形 cap 角）兩者 41/41 仍綠**，沒有測試釘住 margin 與方形 cap 的界限。
- **hvac commit/reopen 其後斷言（scratch 軟斷言複本，流程與測試相同、不停在第一個失敗）。** 10 筆 commit 皆
  COMMITTED、live 非目標比對通過；重開後非目標差異**只有** xref 27／38／51（p5／p6／p7 的 /Page），三者皆
  鍵值集合相同、僅鍵序不同；live==reopen render 在 p5／p6／p7 **實際失敗**（各 8180 px，同一 2× 前像素框
  (1035,561)-(1174,690)，最大通道差 103，與 E 的 image 649 預測一致）；其餘全部通過：10 筆字型資源重用、
  文字狀態欄位、texttrace font/dir/size/color/opacity/type 與首字 origin、2 筆 Tier 1 payload 位元組、三頁
  其他 show 未移動、三頁 mask 外像素差 0。未複製：新增 xref 為 /XRef 的檢查。故 hvac 只剩上述兩個 E 已記錄的
  歸屬問題，其他保真斷言皆綠。

### 2026-09-29 T：收緊 D 的 stroke occupancy 證明（墨跡外擴 relevance）

- **修正（`model/text_commit/stroke_occupancy.py`）。** `relevant` 不再以 path 控制點範圍 ±1pt 篩選，改由
  `_record_is_relevant`：範圍外擴 `_ink_reach + _RELEVANCE_SLACK`，`_ink_reach = hw_max·max(√2, miter 係數) + margin`，
  `hw_max = lw/2·σmax`（新 `_sigma_max` 對任意 CTM 可算；`_similarity_sigma` 改呼叫它，公式只有一份），miter 係數
  miter join 取 `max(1, ML)`、round/bevel 取 1。寬度／ML／CTM 非有限或負、未知 join（含 MuPDF 3 = miter_xps）或 cap、
  範圍非有限 → reach 為 inf → 一律 relevant（NaN 不會讓 record 默默掉出）。relevant 但無法精確建模者照舊拒絕。
  未放寬任何閘；`stroke_record_clears` 與 verify.py 未改。
- **紅燈（修前）。** 新增 `test_separate_stroke_whose_ink_reaches_the_zone_is_refused_at_occupancy[wide-line|miter-vertex|square-cap]`
  （頁框在場，20pt 線中心距 6pt／2pt 線 10 M 頂點距 4pt／12pt 方形 cap 端點距 3pt）、
  `test_square_cap_corner_reaching_diagonally_into_the_zone_is_refused`，及改寫的
  `test_separate_thick_stroke_beside_an_exempted_frame_is_still_refused`（改斷言 occupancy 拒絕、docstring 更正）：
  5 失敗，detail 皆 `raster: growth probe region (163, 172, 176, 193) is not uniform pre-edit`（證明墨跡確在區內，
  且 occupancy 放行）。控制組 `test_the_miter_vertex_bevelled_beside_the_frame_is_admitted`（同幾何 2 j）修前修後皆放行。
- **Mutation 釘住。** `test_stroke_within_the_clearance_margin_is_refused`（頁框自身 path 的 x=133.5 1pt 線，距區 1.5pt）
  修前即綠；`_STROKE_CLEARANCE_MARGIN_PT = 0` 時失敗（raster detail）。方形 cap 對角測試在膠囊半徑去掉 √2 時失敗。
  `_ink_reach` 本身三項也各有釘：`miter-vertex-6pt`（頂點距 6pt，去掉 reach 的 miter 係數即失敗）、
  `test_ink_reach_terms_select_the_separate_stroke[diagonal-square-cap]`（40pt 45° 方形 cap，reach 去掉 √2 即失敗；
  butt cap 同幾何在該 mutation 下放行，證明墨跡來自 cap 角）與 `[separate-within-margin]`（另一條 1pt 線距 2.5pt，
  reach 去掉 margin 即失敗）；三者修前亦為 raster 拒絕（紅）。所有 mutation 皆暫改後還原，`cmp` 確認位元組相同。
- **綠燈。** growth 檔 50 passed；tier1_slice1＋trm_growth_directions 62 passed；
  `test_production_engine_prepares_all_fourteen_real_type0_edits` passed（show26 仍 prepare、K +333）。ruff 全綠、mypy 無錯。
- **未處理（範圍外）。** 無頁框時，path bbox 不碰區但墨跡伸入的粗線不會進 `overlapping`，occupancy 直接回 False，
  只靠 raster 證明（D 之前即存在的 bbox 忽略線寬缺口）。

### 2026-09-29 S：重開後非目標物件改為語意比對（擁有者決定）

- **決定來源。** 擁有者 2026-09-29 決定：重開後的非目標比對改語意比對（§4「存檔重開以語意比對，不比 xref 編號或原始排列」）。
  原因：/Rotate 頁上 `get_text`／`get_texttrace`／`get_drawings` 會切換 set_rotation 弄髒 /Page（產品開檔建頁索引即如此），
  `saveIncr` 以另一鍵序重寫 xref 27／38／51（鍵值相同）。
- **修正（只改 `test_scripts/test_text_commit_real_corpus_acceptance.py`）。** `_assert_only_target_streams_changed` 新增
  keyword `semantic`（預設 False＝原字串逐字比對）。`semantic=True` 時非 stream 物件以 `_objects_semantically_equal` 比：
  字串相同直接相等；否則以產品 bounded tokenizer（`cid_fonts._tokenize`）切 token，測試端 `_semantic_value` 建樹，**只**
  忽略字典鍵序（遞迴）；鍵集合、name（原 token）、literal 字串（原 token）與 hex 字串（bytes）分開標記、參照保留
  generation、陣列保序、數字經 `canonical_pdf_scalar`（精確十進位文字，僅 int/real 同值折疊，即 §2.A；不用
  `canonical_pdf_text` 的 `:.6f`）。重複鍵、解析失敗、編碼失敗、尾端多餘 token 一律視為不等（fail-closed）。
  stream 仍以解碼後 bytes 比對。未改用產品 `parse_pdf_value` 樹：它把 real 轉 float（有損）、丟掉 generation、把
  literal 與 hex 都折成 bytes（`(\101)` 與 `<5C313031>` 會相撞）。
- **呼叫點。** 語意：commit 測試的**重開後**比對、mutation 守門。維持逐字：commit 測試的 live（存檔前）比對——
  記憶體內未重新序列化，E／VERIFY D/E 與本步都實測通過；`test_harness_prepare_measurement_does_not_mutate_the_judged_document`
  ——它要證明 harness 讓檔案逐字乾淨，其紅燈正是鍵序漂移，改語意會使它失效（等於放寬）。
- **紅燈→綠燈。** mutation 守門改為 `(mutate, must_fail)` 參數，並斷言每個 mutation 在重開檔的原始文字確有差異（防空操作）。
  新增 `key-order-only`（對非目標 /Rotate 270 頁 p4 xref 8 呼叫 `get_text`，重開後頂層與巢狀 /VP 字典僅鍵序不同）：
  修前以 `non-target xref 8 changed` 失敗（1 failed, 7 passed），修後通過。其他必須失敗者修後皆以
  `non-target xref <該 xref> changed` 失敗：原有 stream-byte、page-rotate、font-widths，新增
  `number-1-to-0.9999999`（ExtGState xref 10642 `/CA 1`→`.9999999`）、`added-key`（p1 xref 9887 加 `/UserUnit 1`）、
  `reference-target`（p2 xref 1 的 `/GS7 10641 0 R`→`10642 0 R`）。另加純合成
  `test_semantic_object_comparison_ignores_only_dictionary_key_order`（10 組，雙向）：巢狀鍵序、`1`≡`1.0` 相等；
  `1` vs `1.00000000000000000001`（超出 float）、`.3528`/`.3529`、generation、literal vs hex、陣列順序、多鍵、重複鍵、
  未終止字串皆不等。
- **繼承 /Rotate 實體化。** 未特判：若發生會因鍵集合改變而失敗。hvac 50 頁 page dict 皆已有直接 `/Rotate`，本語料不會觸發；
  本次未觸發。
- **驗收（不加 -x）。** 24 項 23 過。唯一失敗 `commits_reopens…[hvac]`：重開後語意比對**通過**，新增 xref 皆 `/XRef`
  檢查**通過**（此檢查在 hvac 上首次執行到），接著停在 `_assert_reopened_renders_match_live` 的 page_index 4（p5），
  1× samples 第 2007900 byte（像素 x=1149, y=561）`0xf9` vs `0xf7`——即 E 記錄的 image 649 live 解碼快取漂移，
  留給下一步。ecc commit/reopen、prepare 14/14、harness、8 個 mutation、10 個語意單元、像素兩個 mutation 皆綠。
  ruff 全綠。
- **pitfall 候選（未寫入 PITFALLS）。** (1) 快照對 stream 只比解碼 bytes，**不比 stream 字典**（/Filter、/DecodeParms 等），
  範圍外未處理。(2) `xref_object`（非 compressed）與 `xref_set_key`／`update_object` 後的輸出鍵序不同；任何
  以字串比對 PDF 物件的測試在 dirty 物件存檔後都會誤報。(3) 產品 `parse_pdf_value` 不適合做「精確相等」：real→float、
  丟 generation、literal/hex 相撞。

### 2026-09-30 G：commit 驗證不再暖 live 文件的 MuPDF image store（擁有者 2026-09-29 決定：修產品）

- **STEP 0（call-counting probe，包 `fitz.Page`／`DisplayList` 方法，只計 live 文件）。** 修前 hvac 10 筆 commit 在 live 上：
  `get_text('rawdict')` 預設旗標 21（`capture_page_state` 11、`_verify_patch_postconditions` 10）、`get_text('text', clip)` 10、
  `get_pixmap(dpi=96)` 20（pre／post 各 10）、`get_image_rects`＋`get_images`＋內部 `get_image_info(xrefs=True)` 各 1、
  `get_drawings` 1（皆 Tier 1 occupancy）、`get_fonts` 32。hvac p5 逐項擾動 1× render（對照 fresh 0）：
  rawdict／dict 預設 23986、`get_image_rects` 19570、`get_image_info(xrefs=True)`／`get_image_bbox` 19570（**皆會解碼**：
  xrefs／bbox 走 hashes，E 記錄的「get_image_info 0」只對無 hashes 版本成立）、**`get_pixmap(dpi=96)` 23934**
  （等於修前 commit 後的實際差異 23934——96 dpi 解碼的 tile 比 72 dpi 所需解析度高，之後 1× render 會重用）；
  0 者：`rawdict(flags=TEXTFLAGS_RAWDICT & ~TEXT_PRESERVE_IMAGES)`、`get_text('text')`、`get_drawings`、`get_texttrace`、
  無 hashes 的 `get_image_info()`、display-list rawdict 去掉 PRESERVE_IMAGES。
- **決定：不採任務建議的「改旗標＋換 image API」。** 只改旗標修不掉 96 dpi raster（V0d 必須 render），且 `get_image_info(xrefs=True)`／
  `get_image_bbox` 同樣解碼；無 hashes 的 `get_image_info()` 失去 xref 篩選、改變 gate 輸入。改為把 commit 的**所有 render／extraction**
  移到 `tobytes(encryption=KEEP)` 快照（任務允許的「tobytes copy」選項，擴及 render）。旗標與 `get_image_rects` 一字未改，
  gate 輸入與修前相同，故不需 14 筆旗標等價證明與 image 幾何等價證明。未用 `store_shrink`，也未用 `pdf_purge_object_from_store`
  之類事後清除（那是暖了再清，且會丟掉使用者自己 render 暖的 tile）。
- **實作。** `verify.ObservedPage(doc, page, pixmap)`＋`observe_page(doc, n)`：快照頁**先** render 96 dpi 再做任何 extraction。
  實測死路：先做 rawdict／`get_image_rects` 再 render，快照上的全解析度解碼會被該 render 重用，pre／post 兩快照 raster 不同
  → V0d 在 image 角落 `(506, 818)` 誤報（合成 628² 噪訊影像）。`capture_page_state(observed=)`、`verify_tier0/1_commit(observed=)`、
  `_verify_patch_postconditions(observed=)`：pixmap、rawdict、span origins、growth glyphs、V0c clip text、V0d、Tier 1 occupancy
  （drawings／image placements／shading／stroke device）讀快照；V0a streams、V0b fonts／annots、operator 重證、V0e 仍讀 live。
  `interpretation` 與 `observed` 互斥（ValueError）。`engine.commit`：apply 前建 pre 快照（失敗 → FAILED `verification_failed`，
  未變更任何東西）；apply 後在既有 revert 保護內建 post 快照（失敗 → VerificationFailure → revert）；`finally` 關閉。prepare／preview
  已在 scratch 上，不變。成本：每筆 commit 多兩次 `tobytes`（hvac 38 MB 約 0.42 s／次）；V0e 自己的 locked reopen 保留未合併。
- **紅燈→綠燈（`test_scripts/test_text_commit_live_store_isolation.py`，合成、CI 會跑）。** `test_committed_live_document_renders_like_a_fresh_reopen`
  [tier0／tier1-growth × rot 0／270]：628² 噪訊影像放 128pt（先在副本上自證 96 dpi 與 rawdict 兩條腿都會擾動 1× render，不會空過）；
  修前 4 筆皆在 live==fresh 斷言失敗，修後綠。另：`test_white_image_in_growth_zone_is_refused_at_image_occupancy`[0/90/180/270]
  （白影像，raster 看不到，detail 必為 `occupancy: image intersects growth zone`）、`test_commit_re_proves_image_occupancy_and_reverts`
  [0/270]（prepare 時猴補放行 image gate，commit 在快照上仍拒絕並還原 stream）——這 6 筆修前即綠，屬覆蓋補強。
  in-memory mutation（腳本、未改檔）：只把 pixmap 改回 live、只把 extraction page 改回 live、只把 `_images_intersect_growth` 改回
  live，三者 rot 0／270 皆使 live≠fresh；control 皆相等。
- **驗收。** STEP 0 重跑：commit 期間 live 上只剩 `get_fonts`；hvac p5／p6／p7 live vs fresh 皆 0。
  `test_text_commit_real_corpus_acceptance.py`（不加 -x）24 passed，含 hvac commit/reopen（live==reopen render 斷言未改），hvac 該測試 64.9 s。
  growth_background_box＋tier0＋interpretation_reuse＋prestate_baseline＋新檔 132 passed。ruff 全綠、mypy 無錯。
- **副作用（實測）。** commit 不再在 /Rotate 頁的 live 上 `get_text`／`get_drawings`，hvac 10 筆 commit 後 `saveIncr`，xref 27／38／51
  原始文字與原檔相同（S 的語意比對仍保留）。
- **PDFModel（實測，未改）。** 合成頁（Hello World＋噪訊影像，rot 0／270）跑 `PDFModel.edit_text`（Tier 0 COMMITTED）＋
  `ensure_page_index_built`：live 上只有 `get_text('dict'/'rawdict', flags=0)`（text_block／`_dict_line_for_runs`）與 `get_text('text')`，
  live vs fresh 0。`pdf_model.py` 的 `_get_chars_in_run_unrotated`（約 2389 行）與選取文字（約 2561 行）用預設旗標 rawdict，會解碼
  影像，但不在文字 commit 流程上（選取／複製路徑）——同類問題，列待辦，未改。同步 `get_page_pixmap` 是 app 自己的 live render，
  不同 zoom 交替本就會共用 tile；背景 render 走 snapshot bytes 不受影響。未處理。
- **pitfall 候選（未寫入 PITFALLS）。** (1) MuPDF image tile 以「≥所需解析度中最接近者」重用：任何高解析度 render／extraction 之後，
  同文件低解析度 render 與 fresh open 不同。(2) `get_image_info(xrefs=True)`、`get_image_bbox`、`get_image_rects` 都會全解析度解碼
  （hash），只有無 hashes 的 `get_image_info()` 不會。(3) 在快照上做驗證時，render 必須先於任何 extraction，否則兩份快照的 raster 不可比。
- **fail-closed 補測（同檔，合成）。** `test_commit_refuses_before_mutation_without_a_pre_state_snapshot`[tier0/tier1]：第 1 次
  `_build_scratch_copy` 回 None → FAILED `verification_failed`、live `get_pixmap` 被猴補為失敗（證明不回退 live）、stream 不變；
  `test_commit_reverts_without_a_post_state_snapshot`[tier0/tier1]：第 2 次回 None → FAILED、stream 還原、chain 為
  `tier0:verification_failed`／`tier0:advance_mismatch, tier1:verification_failed`。**執行方式：plain-Python driver（`_pytest.monkeypatch`），
  非 pytest 行程**（見下方 hang），pytest 執行待補。紅燈：暫改 engine.py 讓兩個 None 分支回退到 live 驗證 → 4/4 失敗
  （pre：`live page rendered without a snapshot`；post：COMMITTED），還原後 `cmp` 位元組相同、4/4 綠。
- **Controller（讀碼，未改）。** `PDFController.edit_text` 成功後 `_invalidate_active_render_state()`＋`show_page(page_idx)`，
  `show_page` 走 `model.get_page_pixmap`＝同步 render live 文件，故本修正是使用者可見的（修前 commit 後的重繪會用到驗證暖的 tile）。
  continuous 模式 `_schedule_visible_render` 的 immediate low 也同步走 `_render_page_into_scene`；不同 zoom 的 live render 彼此共用 tile
  是 app 自身行為，未處理。
- **未完成（證據）。** 額外自加的廣域 pytest（`-k "text_commit or tier0 or tier1 or preview or encrypt" -x`，00:04:01 起）超過 600 s
  被 harness 轉背景，之後 CPU 停在 12.4 s 不動、無可見視窗，成因未定（`-k` 也選到非 text_commit 的 GUI 模組）；依不可 kill 規則未停止。
  任務指定的驗收檔與四個檔均已在前景跑綠；text_commit 全套仍待以前景、`-o faulthandler_timeout=300`、輸出寫檔方式重跑。
- **pitfall 候選 (1) 措辭更正。** 以量測表述：同一文件先做較高解析度的 render／解碼後，較低解析度 render 與 fresh open 不同
  （MuPDF 的 tile 查找規則是推論，未讀原始碼證實）。(3)「快照上 render 必須先於任何 extraction」為本步最重要的新發現。

### 2026-09-30 VERIFY T/S/G（獨立驗證，未改產品碼／測試）

- **T（stroke occupancy）通過。** 新 scratch 腳本、自寫幾何（非測試字串），頁框在場，rot 0／270：(a) 20pt 線中心距 6pt（右側直線與上方水平線兩種）、
  (b) 2pt／10 M、約 11.8° 頂點距 4pt、(c) 12pt 方形 cap 端點距 3pt，全部 `_drawings_intersect_growth` 為 True、detail
  `occupancy: vector drawing intersects growth zone`；288 dpi 單獨渲染確認區內真的有墨跡（60–915 px）。bevel 對照（0 px）照常放行。
  自加 adversarial：`5 0 0 1 cm` 非等向 2pt 線（水平半寬 5pt、中心距 4pt）、零長度 round-cap 圓點（半徑 10、距 8pt）、45° 旋轉 cm
  下 14pt 方形 cap 端點距約 4.5pt，皆被 occupancy 拒絕，無漏洞。記憶體猴補 mutation 跑 growth 檔（control 50 passed）：margin=0 → 2 failed；
  拿掉 clears 的 √2 → 2 failed；拿掉 reach 的 √2 → 1 failed；兩處都拿 → 2 failed；relevance 只剩 1pt slack → 8 failed；reach 拿掉 margin → 1 failed；
  reach 拿掉 miter 係數 → 1 failed。每個 mutation 都有測試抓到。
- **S（語意比對）通過。** 只忽略字典鍵序；另外只有同值數字的寫法會被視為相同（`1`≡`1.0`、`.5`≡`0.5`、`+1`≡`1`、`-0`≡`0`，
  也就是 §2.A 的意圖）。17 組字串 mutation 雙向皆不等：`1`→`0.9999999`、巢狀 `.5`→`.50000001`、加鍵、刪鍵、ref xref、ref generation、
  name 值、鍵名、陣列重排（ref／數字）、literal vs hex 同 bytes、hex 改值、name vs literal、ref vs array、重複鍵、截斷、尾端多餘 token。
  端到端（合成檔 saveIncr→重開→`_objects_semantically_equal` 逐 xref）：只改鍵序（`update_object` 重排）通過；`/CA`→`0.9999999`、加鍵、
  改 ref、改 name、陣列重排都在該 xref 失敗，且每個 mutation 在重開檔的原始文字確有差異。
- **G（image store）gate 輸入不變。** 14 筆依序 prepare→commit（Tier 0 11、Tier 1 3，14/14 COMMITTED）。每筆 commit 前後都比對
  快照頁與 live 頁上 gate 會讀的值：rawdict 文字（font／size／flags／color／origin／逐字 bbox）、影像 block bbox／transform、`get_text`、
  `_span_origins`、halo clip text、`get_drawings`、各 image 的 `get_image_rects`、stroke device records、growth glyph 數、drawings／images gate
  結果，還有 `capture_page_state` 除 pixmap 外的欄位。差異 0；pre pixmap 兩邊也相同。只有 hvac p5/show26 有成長區，gate 結果為 (False, False, 0)。
  影像 gate：3pt 影像放在成長區內（紅／白／藍 × rot 0/90/180/270），prepare 12/12 以 `occupancy: image intersects growth zone` 拒絕；
  猴補讓 prepare 放行後，白色影像 4/4 在 commit 時被快照頁（spy 確認 `page.parent` 不是 live）重新拒絕，stream 也還原。
  紅／藍影像即使猴補放行，prepare 仍被 raster 證明拒絕，無法走到 commit，屬預期。
- **步驟 4 未完成：G 造成一個已證實的測試迴歸。** `real_corpus_acceptance`（不加 -x）24 passed；ruff 全綠、mypy 無錯、lint-imports 4 kept／0 broken。
  `not needs_fixtures` 共 4093 筆，分 4 批：第 1 批 1073 passed、9 skipped；第 2 批 839 passed、12 skipped；第 3 批跑到約 33% 時卡住，
  `test_text_commit_consent_flow.py::test_commit_stage_fallback_confirmation_uses_coded_chain_only` 停在
  `pdf_controller.edit_text → view/message_boxes.show_error`（offscreen 下的 modal，永遠不會返回）。依規則未停止該行程，第 3 批其餘、第 4 批與
  `needs_fixtures` 都未跑。**成因（plain-Python 重現）：** 測試 stub `_fail_live_only(doc, page, prepared, pre_state)` 只收 4 個位置參數，
  G 的 `engine.commit` 改用 `verify_fn(..., observed=...)` 呼叫 → TypeError → engine revert 後重拋（stream 已還原）→ controller `show_error` 卡住。
  同類第二處：`test_text_commit_degrade_visibility.py` 約 475 行同名 stub（同樣走 controller，預期也會卡），未執行。其他 verify stub 都是 `*args, **kwargs`，
  不受影響。G 記錄中「成因未定」的廣域 `-k` 卡住，很可能就是這個（該 `-k` 會選到這兩個檔）。應由測試擁有者修：stub 改收 `**kwargs`，
  非 live 分支原樣轉傳。本步未改。
- **pitfall 候選（未寫入 PITFALLS）。** (1) controller 層測試中，任何非預期例外都會走到 `show_error`；offscreen Qt 下 modal 永遠不返回，
  結果是整個 pytest 卡住而不是失敗，`faulthandler_timeout` 只會 dump、不會結束。(2) 固定位置參數的 verify stub 在簽名加 keyword 後會壞掉，
  stub 應一律收 `*args, **kwargs`。

### 2026-09-30 引擎階段收尾與 UI 階段決策

- 兩個 `_fail_live_only` stub 改收 `**kwargs` 後，consent_flow／degrade_visibility 35 passed；完整套件
  `test_scripts`（含 needs_fixtures）4117 passed、21 skipped、5 xfailed、0 failed。
- UI 設計（唯讀 spec＋對抗式 critique，wf_3ac8a62a-b55）：預設 run 點擊在 14 筆中 6 筆只取到一個字詞
  （索引以空格／字元種類切 run），綁定失敗；既有多 run 路徑以 `origin.x` 排序並補空格，會把鏡射的
  show5 反成「Tank Buffer」、把「設計圖說A版」補成含空格；shipped 預設仍靜默退回 legacy；本機無 Poppler。
- **使用者決策（2026-09-30）**
  1. 必須重建的操作（同頁拖曳、跨頁移動、清空文字、改字型／字級、段落模式）一律經明確的
     「改用重建文字…」與確認；拖曳或樣式操作本身不算同意。
  2. 「run 索引對應單一 show」採**點擊時合併**：Qt-free resolver 證明點到的字詞屬於同一個 show
     （文字、字數相符，union 內無其他 show 原點），目標即整個 show；索引本身不改。
  3. 第二渲染器用 **Poppler**（由 agent 安裝至使用者環境，測試以 `shutil.which` 尋找，本機找不到即失敗）。
  4. 無有效預覽時點擊別處：**保留編輯框與輸入**，顯示等待／拒絕狀態；Esc 才取消。
  - 採預設：等待預覽時保留原圖或上一張已驗證影像並顯示「預覽更新中」；完整存檔重編 xref 後的復原
    誠實回報 `STALE_UNDO`。
- 實作順序依 critique 修正版（umbrella UI 驗收紅燈 → 點擊合併 → commit 端目標 → source_ref →
  token 套用 → generation → 取消靜默 legacy → rebuild redo → 以真結果 finalize → 拒絕原因與重建動作 →
  plan 模式無 CSS 預覽 → 翻預設 → 存檔 → 第二渲染器 → 目視驗收 → 文件）。

### 2026-09-30 G2：點擊時合併 source show（critique 步驟 2，未改索引）

- 新增 Qt-free `model/text_commit/source_run.py`：`group_page_runs` 逐條 extracted line（同 block＋line，
  依 `span_idx` 即 parser 順序，絕不用 `origin.x`）證明「這條 line 的 run 恰為一個 show」才合併：
  (1) 恰一個 reliable-origin show 的原點與第一個 member 原點相距 ≤ 0.05 pt（dict 空間 = frame base 空間；
  base→visual 為剛體轉換）；(2) show 可解碼（Type0 經 ToUnicode，simple font 經 latin-1，與 binding 同兩條腿）；
  (3) 去空白後文字相等、非空白 glyph code 數與 member 非空白字數相等；(4) union bbox 內（嚴格內部）無其他
  reliable show 原點；(5) 該 show 的下一個 show 若 `origin_reliable=False`（續接筆位、位置未追蹤）即拒絕。
  任一失敗 → 不合併，點擊維持原本單一 run（綁定時拒絕，安全）。
- **unreliable-origin 政策**：replay 對未重新定位的續接 show 回報「前一個 show 的原點」（實測 `<Buffer> Tj < Tank> Tj`
  的第二個 show 原點與第一個相同），故這類 show 永不作候選、不參與 foreign-origin 檢查；若它緊接在候選之後則整組拒絕。
- 只讀 content-stream bytes（`xref_stream`）與字型 registry；guard 測試把 `get_text`/`get_texttrace`/
  `get_drawings`/`get_image_rects` 換成會 raise 的 stub，hit 與 outline 都不觸發。
- `SourceRunResolver`（掛在 `PDFModel._source_run_resolver`）以頁為單位快取；每次查詢都重讀 stream 並比對
  `compute_evidence_key` digest，且要求 document 物件與 index run list 物件同一（rebuild／commit／undo 換 list、
  內容變更換 digest，皆自動失效）；另有 `invalidate()`。
- DTO：`model.edit_requests.SourceShowRef(page_xref, stream_xref, op_start, seq, origin)`，origin 為 visual 空間
  （= binding 的 `_origin_in_page_space`，rotate 90 測試釘住），屬 view allowlist 內的 DTO 模組。
  `TextHit` 新增 `source_ref`、`member_span_ids`；run 模式 hit 回傳合併目標（文字 = 解碼後 show 文字、rect = union、
  `target_span_id` = 第一個 member）；`get_text_targets(page, "run")` 每組只回一個項目（union bbox），hover 本來就跟隨 hit。
- 測試 `test_text_commit_source_run.py`（13）：紅燈 9 失敗（'Tank' != 'Buffer Tank'、'A' != '設計圖說A版'、outline
  `['Buffer','Tank','Pump']`、ImportError、hvac p4/show11 `source_ref is None`）；兩 Tj／foreign／successor 三個配對負例與
  guard 在實作前即通過（已標註），foreign 與 successor 以 scratch mutation 證明會轉紅；把排序改成 `origin.x` 的 mutation
  讓 mirrored 與真實 14 筆測試轉紅。實作後 13 passed；真實 14 筆（needs_fixtures）run 點擊最後一個 member 皆得到解碼 show
  文字、`seq` 正確，p6/show5 與 show7 的 ref 不同。
- **延遲（HVAC，0-based page_idx 4/5/6，皆 /Rotate 270）**：stream 45 KB／1.32 MB／1.33 MB。index build 78／89／100 ms；
  resolver cold 142／1438／1613 ms（1.3 MB 頁的 replay 單獨 1.37 s）；warm 0.17／4.9／4.7 ms；hit cold 141／1527／1633 ms，
  hit warm 4.1／6.6／5.5 ms（無合併時 3.5／0.8／0.9 ms）；`get_text_targets` warm 17／10／11 ms。後果：run 模式下每頁第一次
  hover／點擊／outline 繪製，以及該頁每次 commit／undo 之後的第一次，會卡 GUI 執行緒約 1.5 s。**此為步驟 12（預設改 run）
  的阻塞項**；可選方案（未實作）：controller 以 QThread 預熱，或與 preview session 共用 `ReplayEvidence`。
- **已知回歸（B1，步驟 3 修）**：commit 端仍只把被點的單一 run 當 member，合併後的目標經 `edit_text` 會留下其餘字詞。
  合成 `Buffer Tank` → 'Buffer Tanz' 得到頁面文字 `' Tank\nBuffer Tanz\n'`（tier0 `no_source_match` → legacy DEGRADED）。
  完整套件分兩半依序執行：1888＋2241 passed、21 skipped、5 xfailed、**1 failed**：
  `test_edit_text_helpers.py::test_single_line_edit_does_not_push_unedited_text`（hit 變成 'Heading line'，頁面得到
  `' line … Heading lineX'`）。步驟 3 修 B1 時須同時把該測試改為整個 show 的期望值，並加上「不殘留 ' line'」的檢查——
  只改字面值會掩蓋 B1。在步驟 3 完成前本樹不應以 run 模式使用。
- 步驟 U 的 umbrella 模組（`test_text_commit_ui_real_corpus.py`）不在樹中，無法回報其紅燈集合。
- 字型 evidence 在 warm 路徑不重驗：stream bytes 與 run list 都不變、只改字型的變更不會失效（commit 路徑會 rebuild index，故實務上涵蓋）。

### 2026-09-30 C2：commit 端以 group 為目標並攜帶 source_ref（critique 步驟 3、4；修 B1）

- **步驟 3（commit 端重推 group）**：`_resolve_edit_target` 在 run 模式以同一個 Qt-free resolver
  （`model._source_run_resolver`，click 時已暖的 per-page cache）**在 commit 端重推** group，不信任 view 的幾何。
  採用 group 時：members = group 全部 run、`target_span` = 第一個 member、cluster bbox = union（再 ∪ group anchor；
  缺漏的 member 補進 cluster）、reopen anchor 以 `source_run.group_anchor_key`（`show@<id>+<id>…`，單一 member
  仍用 span id）存放——先前單字 anchor 不再縮小 cluster。`_EditTextResolveResult` 新增 `source_group`、
  `reopen_anchor_key`；legacy 的 anchor 遷移改用該 key；hit 的 anchor 迴圈對 group key 只解析到第一個 member，
  不再「就近重綁」。`_tier0_target_from_resolve` 先走 `"source_show"`（在 `dict_line` 之前，不讀
  `get_text('dict')`）：text = 解碼後 show 原文、origin = `source_ref.origin`（binding origin）、bbox = union；
  `whitespace_reconstructed` 為 False，`replacement_for` 原樣。
- **無 ref 呼叫者的政策**：只有「多 member group 且 `original_text` 去空白後等於 show 去空白」才採用 group
  （controller 位置參數路徑、move 等轉送 hit 文字者）；只指名一個字詞者維持舊的單 run 目標——絕不為只指名部分文字的
  呼叫者改寫整個 show（配對負例 guard 測試）。
- **`derive_tier0_preview_target`** 走同一路徑並接受 `source_ref`；新增 `check_no_change=False` 繞過 block 級
  no-change gate（critique minor note：原本只因 'Helvetica'/'helv' 解析不同才沒誤判；紅燈以 monkeypatch
  `_resolve_add_text_font` 取得）。
- **步驟 4（source_ref 傳遞）**：`EditTextRequest.source_ref: SourceShowRef | None`（`model/edit_requests` 內的
  plain DTO）；`pdf_view` 只以 `getattr(info, "source_ref", None)` 轉交（不 import DTO，B4）→
  `TextEditManager.create_text_editor(source_ref=)` → `view.editing_source_ref` → preview payload `"source_ref"` 與
  `TextEditSession.source_ref` → 只在 `view/text_editing.py` 建 request → controller → `EditTextCommand(source_ref=)`
  → `PDFModel.edit_text` → `_resolve_edit_target`。重推的 group 不存在或 `source_ref` 不等 → 新結果碼
  `EditTextResult.TARGET_SOURCE_MISMATCH`（任何 tier／legacy 之前，零變更；controller toast 訊息已加）；
  preview 同樣得 `target_unresolved`。payload 內非 `SourceShowRef` 的值（如 dict）自然比對失敗 → 拒絕（fail-closed）。
- **redo 決策**：legacy 的 undo 以頁面快照還原，page／stream xref 會換號（實測 page 4→10、stream 6→7），ref 永遠
  不再相等；`EditTextCommand` 只在第一次 execute 驗 ref，成功後的重新執行（redo）改走無 ref 路徑，由 target span＋
  整個 show 的 original_text 在還原後的頁上重推 group。Tier 0/1 的 redo 本來就走 patch 重放，不受影響。
- **legacy anchor 遷移**：rebuild（legacy）commit 可能把 grouped show 重新寫成多個 show（htmlbox 路徑實測
  'Heading line'→'Heading lineX' 變成 'Heading'、'lineX' 兩個 show）。原遷移把整個舊 union 的 anchor 種到最近的單字上，
  點 'lineX' 會開成 'Heading'、框住舊 union。改為：多 member group 的 anchor 只遷到新文字**再次證明**的 group
  （新 group key），否則刪除；單一 member 維持原行為。
- **測試** `test_text_commit_source_show_commit.py`（16，含 1 個 needs_fixtures、1 個 Qt）：紅燈 12 失敗／1 guard 通過
  （`REJECTED_STRICT`：mirrored 與 CJK 經 hit 文字皆被 strict 拒絕、`derive` 回 None、no-change gate 回 None、
  payload 無 `source_ref`、新 kwarg `TypeError`）；redo 測試在補上 command 決策前紅（`target_source_mismatch`）；
  legacy anchor 測試在遷移修正前紅（`('lineX', 'Heading')`）。實作後 16 passed：commit 後再點任一字仍合併為同一 show，
  且 `stream_xref`／`op_start`／`seq` 不變（原地 patch）；preview 端 controller 由 ref 推出 `source_show` 目標；mirrored `Buffer Tank`→`Tank Buffer` 單一 show、Tm 不變、Tier 0/1 無 fallback；`設計圖說A版`
  →`設計A圖說版` 碼序完全一致無空白；stale 單字 anchor 仍整個 show commit；twin 的錯 ref 拒絕且 stream、xref 數不變、
  `_apply_redact_insert` 與 `engine.prepare` 未被呼叫；真實 GUI（QTest 點擊＋真 signal）payload 與 request 的
  `source_ref` 等於 hit。Mutation：拿掉 ref 比對 → 兩個拒絕測試轉紅；強制 `source_group=None`（即 B1）→ mirrored／CJK／
  真實語料轉紅。真實 14 筆（needs_fixtures，各自 tmp 副本，strict、max_tier=1）經 `model.edit_text`＋hit 的 ref
  全部無損 commit、解碼等於 replacement——這是 engine＋model 證據，**不是** UI 證據。
- `test_edit_text_helpers.py::test_single_line_edit_does_not_push_unedited_text` 改為整個 show 的期望值（'Heading lineX'）
  並檢查頁面恰為兩行、不殘留 ' line'。
- 回歸：preview_parity／preview_contract／resolve_target_mode／source_run 42 passed；engine acceptance 24 passed；
  完整套件分四段依序（582＋1307＋777＋1480）：4146 passed、21 skipped、5 xfailed，**0 failed**。ruff、mypy、lint-imports（4 kept）乾淨。
- umbrella UI 模組 `test_text_commit_ui_real_corpus.py` 仍不在樹中：狀態 not_run，無紅燈集合可回報。
- 回答使用者問題：「Buffer Tank」在索引中被切成兩個 run，**不需要重建索引**；依 2026-09-30 決策在點擊時合併，本步驟讓
  commit／預覽端以同一 resolver 重推同一個 show。無損（Tier 0/1）編輯後仍是一個 show：索引重建後依然切成兩個 run，
  但點任一個都會再合併。**限制**：走 legacy 重建的編輯可能把文字重寫成多個 show，之後就是分開的兩個目標，重建索引也
  合不回來；這由步驟 7（不再靜默退回 legacy、重建需明確同意）處理。

### 2026-09-30 VERIFY U／G2／C2（獨立驗證，未改產品碼／測試）

- **U**：`test_scripts/` 內沒有 `test_text_commit_ui_real_corpus.py`，也沒有其他 umbrella／ui_real 模組 → 狀態 not_run，
  無 per-case／per-phase 矩陣、無紅燈集合；不以 engine／model 測試代替。
- 執行：source_run＋source_show_commit＋engine acceptance＋edit_text_helpers 85 passed（fixture 在，0 skip）；ruff、
  mypy `model/ utils/`、lint-imports（4 kept）乾淨。完整套件分批依序：4146 passed、21 skipped、5 xfailed、0 failed；
  但 `test_page_render_coordinator`＋`test_page_reorder` 在原批次內 2/2 次 `Fatal Python error: Aborted`（Qt 原生中止，
  `test_page_reorder.py` 159／198 行），兩檔單獨合跑 32 passed；稍早另一次驗證（11:12）也出現同一中止。收集整個 b03 批次
  但以 `-k` 只跑這 32 個測試仍中止 → 觸發點是 b03 某個測試模組的收集期副作用，而 b03 的 34 個測試檔都不在本 diff 內，
  推定早於本 diff（未再二分）。另：前一次嘗試的 b03 中 `test_print_controller_flow` 失敗一次，本次通過，列為間歇性。
- **B5／延遲**：以 wrapper 計數 `fitz.Page`（get_text／get_textpage／get_texttrace／get_drawings／get_image_*／
  get_bboxlog／search_for 等）、`TextPage.extract*`、`Document.get_page_text／extract_font／extract_image`：resolver
  cold／warm、hit、`get_text_targets`、commit 端 re-derive 皆 **0 次**擷取，只有 `xref_stream`、`get_contents`、
  `get_fonts`（font registry）。HVAC p4／p5／p6 cold 148／1508／1573 ms、warm 0.4–5 ms；commit 後第一次點擊再 cold
  （119／1512／1564 ms）。與 G2 紀錄一致：run 仍非 UI 預設（combo 預設段落）時可接受，步驟 12 前必須解決。
- **對抗 grouping（合成，strict）**：同一行相鄰的相同 twins（4 個 run 同 line；Type0／helv、分開 BT、同 BT、Td）
  → 一律不合併（單字 hit，綁定時拒絕，安全但不可編輯）；雙／三空白 show 皆正確合併，helv 版 Tier 0 無損、只改目標 show
  （Type0 版因 k→z 字寬不同以 `advance_mismatch` 拒絕，與 grouping 無關）；
  twins 分行時 ref 各自正確；同原點 twins、不可見 decoy → 不合併。fake-bold 0.3 pt 時點 l0 得到 l1 的 show，
  關掉 resolver 後 hit 也落在 l1（既有 topmost 行為，非 G2），engine 以 `ambiguous_source_match` 拒絕。
- **發現 1（proof 缺口，目前無變更）**：未追蹤筆位的 show D（`10 700 Tm 56 Tc (x) Tj 0 Tc (Buffer Tank) Tj`）畫在
  可靠 show A（72,700 同文字）上、且不是 A 的直接後繼時，D 的 extracted line 被證明為 **A**（seq 0）——(5) 只看直接後繼，
  且沒有「同一 show 只能被一條 line 認領」的檢查。engine 以 `duplicate_source_painter` 拒絕，未改串流。
  判定：不阻擋已完成的 G2／C2，但在任何地方把 resolver 當唯一身分證明（例如步驟 5 的 cache-hit 重新綁定）之前必須修。
- **發現 2（UI 文字不一致）**：TJ 以 kern 造出空白（`[(Buffer) -400 (Tank)] TJ`、Type0 同型）頁面顯示 `Buffer Tank`，
  group 文字卻是 `BufferTank`（去空白比對放行 MuPDF 合成的空白）；`[(Buffer Tank) -500 (Buffer Tank)]` 得
  `Buffer TankBuffer Tank`。綁定的 show 正確，commit 目前以 `tj_multi_item_array` 拒絕；編輯框會顯示和頁面不同的文字，
  日後放行 TJ 陣列時會變成錯誤編輯。
- 使用者問題：不需要重建索引；獨立的兩個 show、前後帶空白的 show、同一行的相同 twins 則維持兩個目標（依設計），
  重建索引也不會合併。
- Pitfall 候選：(a) 未追蹤筆位的 show 可能畫在任何地方，只查直接後繼不夠；(b) 去空白比對會放行 MuPDF 由 kern
  合成的空白，hit 文字不等於頁面文字；(c) 同批 Qt 測試順序相依的原生中止（page_reorder）。

### 2026-09-30 U：umbrella 真實 app UI 驗收（critique 步驟 1；只加測試，未改產品碼）

- **新模組** `test_scripts/test_text_commit_ui_real_corpus.py`（`needs_fixtures`，CI 不跑）。以
  `main.run(argv=[tmp 副本], start_event_loop=False)` 啟動，`from_env` 與 `activate()` 照常執行。
  環境變數設 `TEXT_COMMIT_ENGINE=tiered`、`MAX_TIER=1`、`PREVIEW=plan`，`STRICT`／`CONFIRM_DEGRADE` 維持出廠值。
  不 stub `show_page`、render state、viewport anchor。操作全走真實輸入：頁碼框、F2 模式 action、以鍵盤把 combo 切到 run、
  用 `_doc_rect_to_scene_rect` 對準 show 中段 glyph 中心的 QTest 點擊、Ctrl+A 後 Latin/數字 `keyClicks`、CJK 用
  `QInputMethodEvent` commit、「套用」按鈕、復原／重做／儲存 toolbar action。spy 一律只記錄並放行（preview 回傳、
  `sig_edit_text`、`TieredCommitEngine.commit`、toast、save 路徑）。modal 以記錄器取代並回傳安全預設（No/None）。
  case 表、hash pin 與結構／像素檢查皆 `import test_text_commit_real_corpus_acceptance as acc` 取用，不複製。
  ECC show60 原文只以 hash 比對，訊息先 sanitize 再記錄。
- **分組**：每個 (corpus, page) 一個 app session（hvac-p4／p5／p6、ecc-p0），同頁連續編輯後存一次、重開一次。
  每組把逐案逐階段矩陣寫到 `tmp_path/ui_phase_matrix_<slug>-p<page>.json`，欄位含 case_id、source_sha256、page_index、
  show_seq、HEAD、dirty、dirty_diff_id（`git diff HEAD` 加 untracked 內容的 sha256）、工具版本、各階段狀態與秒數。
- **量測副本要同序列化**：`tobytes` 會丟 object stream，並重寫約 1300 個 HVAC 物件。所以 live 快照只能和 `tobytes` 過的
  基準比，不能和原檔比。原檔只和存檔後重開的檔案比（與 engine 驗收同法）。
- **結果（本機，venv PyMuPDF 1.27，Poppler 25.07.0）**：14 筆的 select／input／preview／apply／undo／redo／second_renderer
  全部 pass。select 是點擊後編輯框文字為整個 show；preview 取得 current token；apply 的 committed token 等於 preview token，
  另檢查原字型資源重用、text-state、只有目標 stream 語意變更、MuPDF 2x 遮罩外 0 像素差、Tier 1 的 K 為最後一項。
  undo／redo 的 stream 與 2x render 都完全還原。Poppler 144 dpi 的遮罩外差異為 0。
  **save_reopen 14/14 fail**：產品存檔（`_save_doc` 增量）每次都用 `embfile_add` 寫入空的
  `__pdf_editor_watermarks`（`[]`）附件，也就改動了 Catalog（加 `/Names/EmbeddedFiles`，`/PageMode` 設成
  `/UseAttachments`；ECC 原本是 `/UseOutlines`），並新增一個非 XRef 物件（hvac 10680、ecc 108）。
  來源是 `model/tools/watermark_tool.py` 的 `_write_watermarks_embed`；沒有任何浮水印也照寫。
  對四個存檔做逐 xref 全掃描（跳過目標 stream）：唯一不同的只有 Catalog（hvac 9886、ecc 103）與新增的 EmbeddedFile，
  沒有其他物件改變。save_reopen cell 另列出全部不符的 xref，只作診斷，不影響判定。
  **注意**：這些綠燈只在 env 覆寫下成立；用出廠預設（`max_tier=0`、`preview=legacy`）時不會有 token。這不是步驟 15 的目視驗收（無 6x 裁切）。
- **負例**：
  - 缺字（hvac p4/show11 輸入 '空調冰水管路系統圖(1)'）**紅**：preview 以 `type0_unicode_unmapped` 拒絕、無 token。
    但按「套用」後靜默走 legacy：DEGRADED、chain `tier0:type0_unicode_unmapped → legacy`，頁面 stream 改變，編輯框關閉
    （finalize apply → committed），並跳出降級 warning toast。
  - 過期 token（p6/show7，打字、等 token、切到 p5 再切回）**紅**：焦點移到頁碼框就觸發 `focus_outside` finalize，
    以切頁前的 token 直接 commit。判定依「切回後才送達的 current-generation token」，因為 token 由內容導出，不能比字串。
  - twins p6 show5／show7（guard，綠）：各自的 ref seq、stream_xref、op_start 正確且互不相同；Esc 後無變更。
  - 快速輸入（ecc show57，guard，綠）：先打 '113.05.04'，在其 preview 仍在跑時改成 '113.05.05'；只有最終文字 commit。
    實測是 coordinator（`_is_current`）直接丟棄舊結果、從未送達 editor（older deliveries=[]），editor 的 generation 檢查沒有用到。
  - IME 組字（ecc show31）**紅**：先以 commit string 輸入 '專案' 並取得 token，再送出只有 preedit 的 '圖名'（offscreen 沒有
    platform input context）後按「套用」，結果 commit 了不含 preedit 的 '專案'。preedit 也讓 generation 由 2 變成 3，並多送出一次
    preview payload。
- **出廠預設測試** `test_shipped_text_commit_defaults_are_the_acceptance_configuration` **紅**（`max_tier` 0≠1、`preview` legacy≠plan），
  要到步驟 12 翻預設才會綠。
- **engine 負例**（`test_text_commit_real_corpus_acceptance.py`）：新增
  `test_production_engine_refuses_a_glyph_missing_from_the_embedded_subset`（guard，綠），Tier 0/1 以 `type0_unicode_unmapped`
  拒絕且 stream 不變。ECC 成長負例**無法還原**：docs/experiments 與 `_evidence_pilot` 只留下遮蔽後的佔位符，故不自編文字、不加測試。
- **預期紅燈 node id**（本機全套件請勿讀成回歸）：
  - `test_text_commit_ui_real_corpus.py::test_ui_commits_every_real_type0_edit_through_the_running_app[hvac-p4|hvac-p5|hvac-p6|ecc-p0]`
    （save_reopen）
  - `::test_ui_missing_glyph_refuses_keeps_input_and_leaves_pdf_unchanged`
  - `::test_ui_stale_token_after_a_page_switch_is_never_committed`
  - `::test_ui_apply_during_an_ime_preedit_never_commits_the_text_without_it`
  - `::test_shipped_text_commit_defaults_are_the_acceptance_configuration`
- **執行時間**：hvac-p4 192 s、p5＋p6 388 s、ecc-p0 約 25 s；缺字、stale、快速輸入與預設約 130 s；twins 61 s；IME 約 10 s。整個模組約 13 分鐘，
  超過單次前景 600 s 上限，需分段以 `-k` 前景跑，例如 `-k "hvac-p4 or ecc"`、`-k "hvac-p5 or hvac-p6"`、`-k "missing_glyph or twin or stale or rapid or ime or defaults"`。
  HVAC 每筆 preview 約 28–31 s，第一次點擊約 10–22 s，Apply 約 17 s（含量測）。
- **Pitfall 候選**：
  - (a) 每次存檔都寫空的浮水印附件，改動 Catalog 與 `/PageMode`，屬使用者可見的非目標變更。
  - (b) `tobytes` 快照和原檔的物件表不可直接比（object stream 被丟，約 1300 物件重寫）。
  - (c) 在編輯中點頁碼框屬於 focus-outside finalize，會以當下 token 直接 commit。
  - (d) HVAC 的 preview 延遲約 30 s，是 plan 預設的 UX 阻塞項，與 B5 的點擊延遲並列。
  - (e) 組字中按「套用」會丟掉 preedit，直接 commit 只含已 commit 字元的文字。

### 2026-09-30 U 重跑（Poppler 已安裝後重新派出；只改測試）

- 全部以前景、每次一個 node id 重跑（HEAD d409c4d、dirty，`dirty_diff_id` 6e473e715c8e；PyMuPDF 1.27.1、PySide6 6.10.2、
  pdftoppm 25.07.0）。14 筆 select／input／preview／apply／undo／redo／second_renderer 全 pass；**save_reopen 14/14 fail，且只有
  一個原因**：每個 cell 只含 Catalog（hvac 9886、ecc 103）變更加一個新增的非 XRef 物件（10680／108），pages／case 錯誤皆空
  （無 render 不符、無遮罩或 text-state 錯誤）——即浮水印空附件，修掉後不會露出第二個紅燈。
- 測試調整：`apply` 階段補上 engine 驗收的 `prepared.font_resource == case.font_resource` 與 `font_xref` 等於 registry 解析值；
  模組 docstring 記錄 ECC 成長負例不可還原（只剩 `[ECC_DWG_LONG]` 佔位符；ecc-4 是已在正向表中的較短 'ECC-3'）。
- **過期 token 測試改寫（先前紅燈歸因錯誤）**：探針證實以真實點擊頁碼框時，焦點先移出，`focus_outside` finalize 在任何換頁
  **之前**以**當下** generation 的 token commit（token 等於最後一次送達的 token；探針中頁碼框這一段是在滾輪來回之後才跑，所以證明的是順序——commit 前沒有任何 `sig_page_changed`——而非 token 剛產生）——屬「有已驗證預覽時點擊別處」，不是過期 token。
  先前的紅燈是測試以 setFocus＋按鍵連送、中間不處理事件，finalize 的 40 ms timer 才落在換頁之後。連續模式下唯一保留編輯框的
  換頁方式是 viewport 上的真實滾輪；改用滾輪到 p5 再回 p6（編輯框全程存在、token 與 generation 不變），按「套用」後以切頁前的
  token commit → **紅**（`stale token committed on Apply after returning`），這才是 §3「換頁使 token 失效」要抓的缺陷。
  另加：若套用被拒，或換頁時編輯框未 commit 就消失，都記為缺陷（輸入必須保留）。
- IME 組字紅燈標為**環境相依**：offscreen 沒有 platform input context；實機 IME 通常在焦點移到「套用」時 commit 或取消組字，
  尚未在實機確認。
- 其餘負例與先前一致：缺字**紅**（DEGRADED、chain `tier0:type0_unicode_unmapped → legacy`、頁面與 xref 27 改變、編輯框關閉、
  降級 warning toast）；twins（guard）綠；快速輸入（guard）綠（第一個 generation 仍在跑時改字，舊結果由 coordinator 丟棄、
  editor 只收到最終 generation）；出廠預設**紅**（`max_tier` 0≠1、`preview` legacy≠plan）。
- 執行時間：hvac-p4 184 s、hvac-p5 186 s、hvac-p6 232 s、ecc-p0 31 s、缺字＋預設 49 s、stale 79 s、twins 60 s、rapid＋IME 13 s，
  合計約 14 分鐘，須分段前景跑。engine 驗收檔 25 passed（236 s）；`ruff check .` 乾淨。
- Pitfall 候選補充：(f) QTest 連送 focus＋按鍵而不處理事件，會把 focus-out finalize 的 timer 延到之後的動作之後，造成假紅燈。

### 2026-09-30 F：修 VERIFY F1／F2（`model/text_commit/source_run.py` 分組證明；先紅後綠）

- **F1（錯綁 show）修法**，兩條規則各自都能擋下 verify 的原反例：
  - 規則 7：未追蹤 pen（`origin_reliable=False`）的 show 一定畫在它最後一次定位的文字行上，沿基線方向無界，垂直基線方向是
    ±`UNTRACKED_BAND_EM`（3 em）的帶。union 碰到這條帶，證明就失敗。帶畫不出界時直接失敗（fail closed）：
    沒有字型證據、Type3、Type0 沒有 Identity-H codec（可能是直書），或文字矩陣奇異。
  - 規則 8：同一頁中，一個 show 最多只能被一條抽取行認領。有兩條行都證明同一個 show 時，兩條都不分組。
  - 舊的「直接後繼」檢查保留（更保守）。
  - 實測 hvac p4／p5／p6 與 ecc p0 沒有任何未追蹤 origin 的 show（215／70／79／62 個 show），所以帶的寬度不會讓已證明的
    group 失效。
- **F2（編輯框文字 ≠ 頁面文字）**：選擇 fail closed，規則 3 為「只有一個字串項且 `Tc == 0` 才分組」。
  - 理由：MuPDF 會從 TJ kern 間隙與 `Tc` 間隙自己合成空白（helv 12 pt：kern -100 不插、-150 插；Tc 1.5 不插、2.0 變成
    'B u f f e r'）。插不插取決於 MuPDF 內部的間隙啟發式，從 stream 位元組證明不了，所以無法證明完全等價。
  - `Tc ≠ 0` 屬同一類缺陷，一併擋下：helv `2 Tc` 讀成 'B u f f e r T a n k'，Type0 `8 Tc` 讀成 '設計圖說A 版'。
  - 單一字串項且 Tc 為 0 時，相鄰字形首尾相接，頁面上只有 show 自己的空白。
  - 語料的 14 筆都是單一項、Tc 為 0（每頁各只有 1 個多項 TJ，不在 case 內），仍然分組。
- **測試**（`test_scripts/test_text_commit_source_run.py`，全為合成 fixture）：
  - 新增 10 個紅燈測試。對修改前的快照跑：10 failed、15 passed。
  - 修改後：25 passed，含 needs_fixtures 的 14 筆語料分組。
  - 成對控制組（修改前後都綠）：`test_untracked_show_on_a_far_baseline_keeps_the_group`、
    `test_single_item_tj_array_still_groups`。
  - 突變證明（M1 移除唯一認領、M2 移除帶、M3 忽略無界帶、M4 帶恆相交、M5 放行多項 TJ、M6 放行 Tc，M7 同時移除規則 7 與 8）：
    分別紅 1／3／2／1／3／2／5 個，每條規則都是必要的。
- **已知限制與可再加固之處**：
  - Form XObject 內畫的文字 replay 看不到，但若它的重畫產生第二條認領行，規則 8 仍會拒絕。
  - 規則 8 只計算「完整證明」的行。有可靠 origin 的畫者（例如用 TJ kern）在 A 的 origin 重畫**不同**文字時，那條行自己證明
    失敗，A 的行照樣分組。這不算錯綁，因為那條行確實是 A；可加固為在候選階段就計算認領數。
- **回歸**：
  - source_show_commit、live_store_isolation、edit_text_helpers：62 passed。
  - add_textbox_atomic、char_run_reconstruction、cross_page_text_move：18 passed、1 skipped。
  - engine 語料驗收：25 passed（211 s）。
  - `ruff check .` 乾淨；mypy 55 檔無問題；lint-imports 4 kept、0 broken。
- **umbrella 重跑**（Poppler 25.07.0，分四段前景跑）：
  - 14 筆的 select／input／preview／apply／undo／redo／second_renderer 全部 pass。
  - save_reopen 14/14 fail，原因仍只有浮水印空附件（Catalog 9886／103，新增 10680／108）。
  - 缺字紅、stale token 紅、IME 紅（環境相依）、出廠預設紅，都與先前紀錄一致；twins、rapid 綠。
  - 沒有因 F 而新增的紅燈。
- Pitfall 候選：
  - (a) 未追蹤 pen 的 show 可以畫在它文字行上的任何位置，只檢查直接後繼不夠。
  - (b) 去空白比對會接受 MuPDF 由 kern 或 Tc 合成的空白，造成編輯框文字和頁面不同。
  - (c) 用 subprocess 擷取 pytest 輸出時要指定 `encoding="utf-8"`，否則 cp950 解碼會讓 reader thread 崩潰。

### 2026-09-30 W：存檔在沒有浮水印時不再改動非目標物件（`model/tools/watermark_tool.py`；先紅後綠）

- **根因（STEP 0）**：`WatermarkTool.prepare_doc_for_save` 在浮水印為空時無條件呼叫 `_write_watermarks_embed(doc, [])`。
  `ToolManager.prepare_doc_for_save` 預設傳入 live `self.doc`，所以在增量存回原檔之前，live 文件就被刪除再 `embfile_add` 一個 `"[]"` 附件：
  Catalog 多出 `/Names/EmbeddedFiles` 與 `/PageMode/UseAttachments`（閱讀器會打開附件窗格），並新增 EmbeddedFile 串流等物件。
  這正是 umbrella save_reopen 14/14 紅燈的唯一原因（Catalog hvac 9886／ecc 103，新增 10680／108）。
- **修法**：浮水印為空時，只有文件**已帶**浮水印附件才走舊路徑（刪除後改寫成 `"[]"`，已釘住：移除後重開不再載入）；
  沒有附件就完全不碰文件（Catalog 不變、不新增物件）。`embfile_names()` 讀取失敗時視為「有附件」，照舊路徑清除（fail closed，
  不留舊資料）。加密、另存新檔、原子完整存檔、secure-save 政策都沒動；有浮水印時的 clone 路徑不變。
- **測試**（`test_scripts/test_watermark_save_noop.py`，合成、CI 可跑）：經 `PDFModel.save_as` 增量存回原檔，Catalog 語意不變、
  沒有新增非 XRef 物件、沒有附件；`prepare_doc_for_save` 不改 live 文件 → 修改前 **2 failed**（Catalog 多出 `/Names`…`/PageMode/UseAttachments`），
  修改後 5 passed。guard（修改前後都綠）：浮水印存檔往返、移除後存檔不再載入（附件內容為 `[]`）、names tree 讀取失敗仍走清除路徑。
- **回歸**：含 `save_as`／`watermark` 的 31 個測試檔加 optimize workflow、print settings persistence：457 passed、5 skipped
  （`test_print_fileless` 的 Windows 0x80040155 faulthandler 傾印為既有非致命訊息，測試通過）。`ruff check .` 乾淨。
- **umbrella**（Poppler 25.07.0，四個頁組一次跑，738 s）：14 筆 select／input／preview／apply／undo／redo／**save_reopen**／second_renderer
  **全部 pass**；save_reopen 由 14/14 fail 轉為 14/14 pass，沒有露出第二個紅燈。
- **遺留**：先前由本編輯器存過的檔案都帶 `"[]"` 附件，仍會在每次存檔時被刪除重寫（Catalog 變動）；可再加「既有附件已是空清單就不動」，
  但本步驟依規格保留既有清除行為。
- Pitfall 候選：(a) 存檔時的 tool hook 在沒有東西要保存時仍改動 live 文件；`embfile_add` 還會設定 `/PageMode/UseAttachments`。

### 2026-09-30 T5：依 token 套用（critique 步驟 5；修 B2；先紅後綠）

- **engine**：新增 `TieredCommitEngine.cached_candidate_identity_failure(page, prepared, target_text=, expected_origin=)`，
  cache hit 在 commit 前於 **live 頁**重新綁定：先比 `page.xref`、`page_fingerprint`，再以 engine 的 font registry 跑
  `bind_source_text`（沒有 registry 時 CID 文字無法解碼），要求 `stream_xref` 與 `op_start`／`op_end`／`string_start`／
  `string_end` 全等（`seq` 只是序號），且 splice 落在該 show 的 **operator 範圍**內——Tier 1 是整個 operator 的 transplant
  （`op_start..op_end`），不是只有字串；第一版用字串範圍，umbrella 的 hvac p4/show26 與 ecc show60（Tier 1）因此 apply 0 次
  commit，已補合成紅燈 `test_tier1_cached_candidate_rebinds_and_commits` 後修正。只讀 stream bytes 與 font registry。
- **`_attempt_tiered_commit`**（有 `plan_token` 時）：identity 不符 → `RejectReason.PREVIEW_STALE`；cache miss 重新 prepare，
  只有新 token 等於 request 的 token 才 commit，拒絕或 token 不同都回 `PREVIEW_STALE`；token 綁定的 commit 得到 `STALE_PLAN`
  也轉成 `PREVIEW_STALE`；有 token 但 commit 端推不出 target 同樣 `PREVIEW_STALE`。style／geometry override 與 shared-stream
  維持原 reason（`test_text_commit_candidate_identity.py` 釘住；preview 本身也拒絕 override，所以這種 token 不可能相符）。
  `edit_text` 在 strict 與 consent／legacy 分支**之前**把 sentinel 轉成終止結果 `EditTextResult.PREVIEW_STALE`
  （chain `tier0:preview_stale`，絕不進 degrade notice）。
- **pending**：`EditTextRequest.requires_preview_token: bool = False`（只有 inline「套用」在 plan preview 開啟時設定）；
  沒有 token → `EditTextResult.PREVIEW_PENDING`，在任何 resolve／tier／legacy 之前，零變更。`allow_rebuild: bool = False`
  先加欄位，目前只豁免此 gate（語意留給步驟 7）。兩者經 controller → `EditTextCommand` → `PDFModel.edit_text` 傳遞；
  command 的重新執行（redo 無 forward patch）改傳 `plan_token=None`、`requires_preview_token=False`（與 source_ref 同一決策；
  `command.plan_token` 屬性保留）。
- **controller**：兩個新結果碼有 `_edit_result_to_message` 文案（皆含「文件未變更」），走 `_show_notice_feedback`
  （warning toast；沒有 toast 介面時只記 log），**不會**落到 `show_error`。`activate()` 依 `settings.preview == "plan"`
  呼叫 `view.set_text_plan_preview_required()`；出廠預設（legacy preview）不需要 token，行為不變。
- **view**：editor 新增 `plan_token_state_changed` signal（generation 變動、CSS 暫態、plan raster 被接受時發出）；
  `TextEditManager.apply_permitted()` 決定「套用」是否可按：plan 模式下必須有 current-generation token；未修改的 session、
  拖曳過或跨頁的 editor（步驟 7／10 前維持 tokenless，**暫行**）例外；改字型／字級沒有已驗證預覽（preview 拒絕 override）
  → 維持停用。`_on_text_apply_clicked` 在不允許時不 finalize、保留編輯框與輸入。Cancel 不受影響。
- **發現並修正（先紅後綠）**：按下**停用中**的「套用」時，Qt 把焦點交給第一個 ClickFocus 祖先 `rightPanel`（在編輯脈絡之外），
  40 ms 後 `FOCUS_OUTSIDE` finalize 以 tokenless 請求 commit 未驗證的文字並關閉編輯框——等於繞過 gate。修法：
  `text_card.setFocusPolicy(Qt.ClickFocus)`，按在文字設定卡片的停用子元件或空白處時焦點留在卡片（屬編輯脈絡）。
  副作用：點文字設定卡片空白處不再結束編輯（先前會 FOCUS_OUTSIDE commit）。
- **測試**（`test_scripts/test_text_commit_apply_by_token.py`，17，全合成）：紅燈 12 failed／3 passed（實作前）：twin 錯目標
  （A 的 token、B 的 ref、同 replacement → 修改前 **A 被改寫**）、文件變更後 stale（cache hit 走 STALE_PLAN → legacy；
  cache 清空則靜默重新 prepare 並 commit）、不同 replacement 的 cache miss、pending、`allow_rebuild`、預設欄位、redo 不帶 gate、
  兩個 toast 路由、View「套用」等 token；之後再加的兩個紅燈：按停用中的「套用」（修改前 commit 並關框）、Tier 1 cache hit
  （修改前 `PREVIEW_STALE`）。guard（前後皆綠，已標註）：清空 cache＋相同 token commit、自己的 token commit、tokenless 呼叫者。
  突變：拿掉 identity 檢查 → twin 與 stale[hit] 轉紅；拿掉 token 相等檢查 → stale[cleared] 與不同 replacement 轉紅。
- **既有測試遷移**：`test_text_edit_rotated_page_gui.py` 三個測試在 setPlainText 後立刻按「套用」。探針證實它們原本是透過
  「按到停用按鈕 → FOCUS_OUTSIDE」commit，並沒有走 Apply；改為先等「套用」可按（有 current token）再按，並加上 request 帶
  `requires_preview_token` 與 token 的檢查（沒有放寬斷言）。
- **延遲**：rebind 在 HVAC p4／p5／p6 為 64／1530／1560 ms（`bind_source_text` 重新 replay 1.3 MB 串流），加在 GUI 執行緒的
  Apply 上；可再與 click-time resolver 或 preview 的 `ReplayEvidence` 共用 replay（未做）。
- **umbrella**（Poppler 25.07.0，分四段前景跑）：14 筆 select／input／preview／apply／undo／redo／save_reopen／second_renderer
  **全部 pass**；缺字負例**由紅轉綠**（無 token → 套用停用，PDF 不變、編輯框與輸入保留）；twins、rapid 綠；stale（換頁後回來）
  仍紅——token 與 generation 都沒變，candidate 在 live 頁仍完全有效，rebind 通過，屬「換頁使 token 失效」的 view 端需求（本步驟外）；
  IME（環境相依）與出廠預設仍紅，與先前一致。
- 回歸：preview_contract／parity／consent／degrade／candidate_identity／source_run／source_show_commit／rotated GUI／GUI
  regressions／intent／default_engine_ux／edit_text_helpers／live_store_isolation／interaction_modes 299 passed；engine 驗收 25 passed；
  完整套件分 8 批前景（排除 umbrella 與 engine 驗收）4156 passed、21 skipped、5 xfailed、0 failed。ruff、mypy（55 檔）、
  lint-imports（4 kept）乾淨。
- **未處理（交給後續步驟）**：click-away／FOCUS_OUTSIDE 在沒有 token 時仍以 tokenless commit 並關框（使用者決定是保留編輯框，
  屬步驟 9）；font／size 變更不 bump generation（步驟 6）；換頁不使 token 失效。
- Pitfall 候選：(a) 按下停用的按鈕會把焦點交給第一個 ClickFocus 祖先，可能觸發 focus-out finalize；(b) Tier 1 的 splice 是
  整個 operator，不是字串範圍；(c) token 只是名稱，cache hit 必須在 live 頁重新綁定（twin 的文字與 replacement 相同）；
  (d) `bind_source_text` 沒有 registry 時 CID 文字一律 `undecodable_target`。
- 2026-09-30 UI 步驟 6（font／size／drag 使 generation bump）：**缺陷**：generation 只在 `textChanged` 的 handler bump，
  font／size handler 走 `configure_render_context` → `_regenerate_preview`，仍在**同一 generation** 送出新請求；變更前已在飛的
  結果（同 generation）之後抵達仍會 `apply_plan_preview` 成功並設 token（Apply 亮起，卻不是使用者現在看到的樣式）。拖曳同理
  （`new_rect` 改變，但 generation 不變）。**修法**：`PreviewBackedInlineTextEditor.configure_render_context` 為 chokepoint——第一次
  之後任何 render 輸入（字型、字級、色彩、幾何）實際改變即 `_plan_generation += 1`（同值不 bump，首次呼叫不 bump，故 gen 1 契約不變）；
  新增 `invalidate_plan_preview(*, regenerate=True)`（bump＋清 `_plan_preview_active`＋`plan_token_state_changed`），PDFView 在拖曳
  每次 move 呼叫 `regenerate=False`（只 bump，不洗請求），放開後 `editing_rect` 更新完再 `regenerate=True` 重新請求（帶新的
  `new_rect`），避免拖回原位後編輯框卡在無 token。View 仍只 emit 請求，不碰 Model／PDF。
- **測試（先紅後綠）**：`test_text_commit_preview_contract.py` +5（字型／字級 in-flight 結果被拒、新請求自己的結果被接受；
  拖曳 invalidate 不洗請求／放開才請求）；`test_text_editing_gui_regressions.py` +2（drag move 只 bump、release 重新請求，
  真實 `_mouse_move`／`_mouse_release`）；`test_text_commit_apply_by_token.py` +2（真實 handler：token 已就緒→改 size／font→
  舊 generation 結果抵達 → 回 False、token None、Apply 停用、送不出請求、PDF 不變）。紅燈 7 failed（`2 > 2`、
  `no attribute invalidate_plan_preview`、`[] == [False, False]`）。guard（前後皆綠，已標註）：既有 token 在 restyle 後清除、
  同值／首次 configure 不 bump。
- 回歸：preview_contract／parity／gui_regressions／apply_by_token／rotated GUI／no_jump／font_size_input／interaction_modes／
  edit_text_helpers 586 passed、6 skipped。umbrella（Poppler 25.07.0，分兩段前景）：14 筆 real-edit 全 pass；missing-glyph、twins、
  rapid 綠；stale-after-page-switch、IME、出廠預設仍紅（與步驟 5 相同，非本步驟範圍）。ruff 乾淨。
- Pitfall 候選：(a) 在飛的非同步結果以 generation 相等判定新鮮，任何會改變預覽輸入的操作（不只 text）都必須 bump，否則同 generation
  的舊結果可設 token；(b) 集中在 `configure_render_context` 這類 chokepoint bump，而非每個 handler 各記一次。

### 2026-09-30 VERIFY U／F／W／T5／步驟 6（獨立驗證，未改產品碼／測試）

- **umbrella 自己重跑**（Poppler 25.07.0，PyMuPDF 1.27.1，PySide6 6.10.2，分三段前景）：14 筆 select／input／preview／apply／undo／
  redo／save_reopen／second_renderer **全部 pass**（hvac-p4 6、p5 2、p6 2、ecc-p0 4）；存檔只走 `_save_doc`、只有一個「儲存完成」
  information、save errors 全空、無 toast。負例：missing_glyph、twins、rapid **綠**；stale-after-wheel-page-switch、IME（環境相依）、
  出廠預設 **紅**，與 T5／步驟 6 紀錄一致。
- **umbrella 真實性**：`main.run` 啟動；`show_page`／render state／anchor 未 stub；點擊為 QTest 滑鼠、輸入為 keyClicks／
  `QInputMethodEvent`、Apply 為真按鈕點擊（停用時點不到 → 0 commit 即 fail）；spy 全部 pass-through；modal 記錄後回安全預設。
  與 engine 驗收檔的差異（皆不阻擋，因重開 render 與 live render 2x 逐像素相等，且遮罩內必須有變化）：live 非目標物件用
  `semantic=True`（engine live 為 exact）；save_reopen 沒有對重開檔重跑 `_trace_for`（font／size／color／dir／首字 origin）與
  非目標 show origin，只在 live 快照檢查；正例 Apply 沒斷言 `requires_preview_token is True`／finalize reason 為 APPLY
  （帶同一 token 的 FOCUS_OUTSIDE commit 也會過）；進模式與 undo／redo／save 用 `QAction.trigger()`（同 shortcut slot，非字面按鍵）。
  以上列為加固項。
- **F**：重跑 F1 反例（未追蹤筆位 D 疊在 A 上，四種變體）→ 全部不分組（seq None）；F2 反例（多項 TJ、kern）→ 不分組，不再出現
  `BufferTank`。新增 `Tc`／`Tw`（2–20）／`Tz 300`／`'`／`"` 掃描：凡分組者頁面文字皆等於 group 文字；`Tw ≥ 10` 時 MuPDF 拆成兩行而不分組。
- **W**：`_write_watermarks_embed` 只剩兩個呼叫點（空清單＋已有附件、clone 路徑），沒有其他 `embfile_add`；5 個測試通過。
- **T5／步驟 6 對抗（真實 app，合成 helv 文件，probe `vx_token_probe.py`）**：
  - twins：編輯框在 twin2 有 token 時直接點 twin1 → click-away 以 twin2 的 token commit 到 twin2（正確），twin1 另開、另 commit，無錯目標。
  - 打字後不處理事件立刻按「套用」→ 停用、不 commit；新 token 到達後只 commit 最終文字。
  - 編輯框開著時按 toolbar「復原」（改動同頁）→ token 與「套用」仍有效；按「套用」得 `PREVIEW_STALE`（PDF 不變）但**編輯框關閉、輸入遺失**；
    view 在文件變更時不會使 token 失效。
  - **缺陷（既有，非本 diff；blame f084f0b2，2026-06-05）：開啟另一份文件時，編輯中的文字被 commit 到新文件。**
    `PDFController.open_pdf` 先 `model.open_pdf(..., append=True)`（切換 active session），之後 scene 重建才 finalize 編輯框，
    request 因此套在新文件上。無 token 時：Tier 0 直接改寫新文件同位置／同文字的 show（run 模式同版面；**段落模式（出廠預設）不同版面也會**），
    或 preview 拒絕的文字經 legacy DEGRADED 寫進新文件；原文件不變、輸入遺失。有 token 時：新文件內容不同 → T5 的 fingerprint 擋成
    `PREVIEW_STALE`（PDF 安全，但輸入遺失、toast 誤導）；**新文件是位元組相同的副本（另一路徑，例如下載的「(1)」）→ 以已驗證的 token
    直接 commit 到副本**（page xref、fingerprint、rebind 位移全等，token 由內容導出），即有已驗證預覽也擋不住。對照組：切換到已開啟的分頁會先 finalize 再 `activate_session`，commit 落在原文件。
    最近開啟檔案選單直接 emit `sig_open_pdf`，即使用者可達路徑。critique 步驟 7–16 沒有「換 session 前 finalize」的項目，需新增。
  - 無已驗證預覽時點畫布空白處 → tokenless CLICK_AWAY → `tier0:encoding_failed → legacy` DEGRADED commit（文字被重排），只有降級 toast（步驟 7＋9）。
- 步驟 14：second_renderer 的綠燈只在設定 `PDF_EDITOR_PDFTOPPM` 時成立；未設定時 `shutil.which("pdftoppm")` 為 None（Poppler 不在 PATH），14 筆該階段會 fail。
- 檢查：新模組＋preview_contract＋rotated GUI＋edit_text_helpers 142 passed；engine 驗收 25 passed；ruff、mypy（55 檔）、lint-imports
  （4 kept）乾淨。完整套件（266 檔，排除 umbrella 與 engine 驗收，8 批前景）4165 passed、21 skipped、5 xfailed、0 failed；本次未出現 Qt 原生中止。
- Pitfall 候選：(a) 開新文件時 active session 在 finalize 之前切換，未 commit 的編輯會落到新文件；(b) 文件在編輯框開著時被改動
  （undo／redo），view 端 token 不失效，只靠 model 端 fingerprint；(c) umbrella 以 token 相等判定 Apply，無法區分 APPLY 與 FOCUS_OUTSIDE。

### 2026-10-01 S7：不再默默走 legacy（critique 步驟 7；擁有者 2026-09-30 決定；先紅後綠）

- **model**（`model/pdf_text_edit.py::edit_text` 的 tiered 分支）新順序：`PREVIEW_STALE`（終止）→ `strict` 仍回 `REJECTED_STRICT`
  （有沒有同意都一樣）→ **未帶 `allow_rebuild` → 新結果碼 `EditTextResult.REJECTED`**，`last_commit_outcome` 為 REJECTED，
  `degraded_reason` 是真實原因碼，chain 只有 `tier0:<reason>`（沒有 `legacy`），零變更，不論 strict 與否都不進 legacy →
  帶 `allow_rebuild` 但 `confirm_fallback is None` → `FALLBACK_DECLINED`（缺 callback 不算同意）→ 有 callback 才詢問（預設否），
  同意後才 legacy。tiered 分支若既無 outcome 也無原因，以 `tiered_refusal_unknown` 拒絕，不會落到 legacy。
  `engine="legacy"`（kill switch）與 `shadow` 不經 tiered 分支，行為不變。
- **request**：`EditTextRequest.allow_rebuild` 取得同意語意（只由之後的「改用重建文字…」設定；每個 request 各自有效，不沿用）；
  `MoveTextRequest.allow_rebuild: bool = False` 新增；`controller.move_text_across_pages` 的舊式 kwargs 也接受 `allow_rebuild`。
- **controller**：`_fallback_consent_callback(allow_rebuild)` 只在 request 帶 `allow_rebuild` 時傳 `_confirm_legacy_fallback`，
  **`TextCommitSettings.confirm_degrade` 與 `TEXT_COMMIT_CONFIRM_DEGRADE` 已移除**。`REJECTED` 有文案（只含原因碼，
  「…（原因：<code>），已取消（文件未變更）」），走 warning toast（`_PREVIEW_NOTICE_RESULTS`），不走 `show_error`。
  同頁移動改成把一個 `EditTextRequest`（帶 move 的 `allow_rebuild`）交給 `edit_text`；**跨頁移動（critique B3）**：同意在 `try`、
  snapshot、刪除與 `add_textbox` 之前決定——沒有 `allow_rebuild` → `REJECTED`（原因碼 `cross_page_move_requires_rebuild`），
  完全不呼叫 model；有 → 只問一次（chain `("cross_page_move_requires_rebuild", "legacy")`），拒絕 → `FALLBACK_DECLINED` 且
  `add_textbox` 不會執行；同意 → 來源刪除以 `allow_rebuild=True` 加上「已同意」callback 執行，不會再問第二次。
  **決定**：`engine="legacy"` kill switch 下跨頁移動不需同意（與該 engine 的原地／拖曳編輯一致，都是明確選擇的重建）；
  settings 不明時照樣要求同意（fail-closed）。
- **redo**：`EditTextCommand` 對已確認過的重建，重做時改傳預先核准的 `_replay_confirmed_fallback`（原本傳 None，新規則下會變成
  DECLINED）。步驟 8（以 after-snapshot 重做）會取代這條路。
- **使用者決定的涵蓋面**（全部經測試）：同頁拖曳（`geometry_override_present`）、跨頁移動（刪除＋`add_textbox`）、清空文字
  （`empty_replacement`）、字型／字級（`style_override_present`；只改字型而文字未變時，gate 順序先回 `no_change`，見 pitfall (c)）、
  段落模式（`multi_span_target`）、tokenless click-away（驗證報告的點畫布空白處：現在 `REJECTED`、PDF 不變、不進 legacy）。
- **紅燈**（`test_scripts/test_text_commit_no_silent_legacy.py`，實作前 18 failed／5 passed）：出廠預設（strict=False）缺字
  → 修改前 `legacy redact+reinsert engine reached`；`allow_rebuild` 無 callback、拖曳、清空、字級、段落、tokenless 請求、跨頁／同頁移動
  未同意（`AttributeError: REJECTED`、`MoveTextRequest ... unexpected keyword argument 'allow_rebuild'`）、`confirm_degrade` 仍存在；
  真實 View 點畫布空白處（subset Identity-H 缺字）→ 修改前 `_apply_redact_insert` 被呼叫一次。5 個 guard（前後皆綠，已標註）：
  出廠預設 strict=False、拒絕 callback 的 DECLINED、同意後重建、strict＋同意仍 REJECTED_STRICT、同意過的重建 redo 不再詢問。
  之後補 1 個：legacy kill switch 跨頁移動不詢問。移動測試改用單一 token 頁（`_resolve_cross_page_move_source_span_id` 的排序
  fallback 有既有缺口，同 degrade_visibility 的做法直接帶 span id）。最終 24 passed。
- **既有測試遷移**（共 60 個失敗測試、17 檔；以暫時的 scratch pytest plugin 追蹤每個走到 REJECTED 的測試，另找出 7 個
  「因拒絕而空泛通過」的測試一併遷移——`test_text_commit_characterization.py` 5 個 strict xfail 改成因拒絕而 xfail、
  `test_char_run_reconstruction.py` 2 個段落拖曳）：
  - 主體是 legacy／重建路徑、直接呼叫 model 的測試 → 在該測試的呼叫加 `allow_rebuild=True` 與接受的 confirm stub
    （與原本同一條 tiered→legacy 路徑，只是有同意）：`test_edit_text_helpers`（9）、`test_text_editing_fidelity_suite`（`_edit_block`，
    13 個編輯測試都用它）、`test_overlap_textbox_edit`（5）、`test_char_run_reconstruction`（5）、`test_edit_geometry_stability`、
    `test_week1_model_regressions`、`test_short_term_safety`、`test_1pdf_horizontal`、`test_empty_text_edit`、
    `test_text_commit_maintenance`（2）、`test_text_commit_persistence`（1）、`test_text_commit_shadow_mode`（1，並斷言詢問的 chain）。
  - 主體是 legacy engine 本身 → `engine="legacy"`：`test_text_commit_characterization`（模組本來就寫「legacy 路徑的特性描述」）、
    `test_text_geometry_page_rotation::test_legacy_edit_keeps_place…`（舊註解「預設 = legacy」自 T16-3 起已過時）。
  - View 驅動、主體是 GUI／undo 管線，而 View 在步驟 10 前送不出同意 → `engine="legacy"`：`test_multi_tab_plan` 新 fixture
    `mvc_legacy`（03、19ab、19ac、19c、19d、19e、19h）、`test_no_jump_editor_geometry::test_reopen_same_textbox_cycles…`。
  - 跨頁移動 → request 帶 `allow_rebuild=True`＋confirm stub：`test_cross_page_text_move`（5）、`test_text_commit_degrade_visibility`
    （2 個移動；`_edit_via_signal` 預設帶同意，`_launch` 本來就自動確認）、`test_text_commit_consent_flow`（全部改用 request 同意，
    包含「不會詢問」的三個情境，否則 gate 未武裝、斷言空泛）。
  - `test_text_edit_manager_foundation::test_controller_accepts_move_text_request`：同頁改道現在傳一個 `EditTextRequest`，
    斷言改為逐欄位比對（多檢查 original_text、span id、mode、`allow_rebuild is False`，沒有放寬）。
  - **政策釘選改寫（刻意改變的行為）**：`test_text_commit_default_engine_ux::test_shipped_default_never_prompts_for_consent`
    （T16-3 釘的是「默默 legacy＋一則降級通知」）→ `…never_prompts_and_never_falls_back`（REJECTED、零變更、無降級通知、一則
    toast）；兩個 `confirm_degrade` opt-in 測試 → `test_explicit_rebuild_request_…`；`test_stale_undo_tells_the_user…` 的第二次
    legacy 編輯改帶同意；`test_text_commit_settings` 兩處改成斷言欄位已不存在。
- **暫時的 UX 代價（步驟 9／10／12 前）**：(1) 出廠預設仍是 `max_tier=0`、`preview="legacy"`，Tier 0 拒絕的普通編輯（T16-3 量到
  12/12）現在一律拒絕並顯示 toast，不再默默重建；(2) T5 讓拖曳過／跨頁的 editor 仍可按「套用」，現在會得到 REJECTED，而 finalize
  仍會關框、輸入遺失（步驟 9）；(3) View 還沒有「改用重建文字…」（步驟 10），所以拖曳、跨頁移動、清空、改字型字級在 tiered 下目前
  沒有任何可完成的路徑。
- **檢查**：no_silent_legacy 24、consent_flow、degrade_visibility、default_engine_ux、settings 與全部遷移檔 547 passed、7 skipped、
  5 xfailed；完整套件（267 檔，排除 umbrella 與 engine 驗收，8 批前景）**4189 passed、21 skipped、5 xfailed、0 failed**；engine 驗收
  25 passed；umbrella（Poppler 25.07.0，四段前景）14 筆 × 8 階段全 pass（hvac-p4／p5／p6、ecc-p0），missing_glyph、twins、rapid 綠；
  stale-after-page-switch、IME、出廠預設仍紅（與先前相同，非本步驟範圍）。ruff、mypy（55 檔）、lint-imports（4 kept）乾淨。
- 文件未改（依指示）：`docs/ARCHITECTURE.md`（:302、:319–322、:701–702、:746 仍描述 `confirm_degrade`）與 `TODOS.md`（:1622、
  :1652 的歷史紀錄）留給步驟 16。
- Pitfall 候選：(a) 「缺少 callback」與「同意」必須分開：舊 API 把 `confirm_fallback=None` 當成「不問直接 legacy」，同意語意
  改掛在 request 旗標後，None 必須是拒絕，且 redo 的「重播已確認決定」要改傳預先核准的 callable，不能再傳 None；
  (b) 行為政策翻轉後，靠舊行為的測試會「空泛通過」而不是失敗（characterization 的 strict xfail、斷言「文字還在」的拖曳測試）——
  要追蹤實際走到新拒絕分支的測試，而不是只看失敗清單；(c) plan gate 先檢查 `no_change` 再檢查 style／geometry override
  （順序由 structural gates 測試釘住），所以只改字型時的拒絕原因碼是 `no_change`，步驟 10 的文案要依 request 內容對應；
  (d) 跨頁移動的同意必須在 `try` 與 snapshot 之前決定：在 `try` 內拒絕會丟 RuntimeError → `replace_active_document_from_snapshot`
  （換掉 document handle，本身就是變更）→ modal `show_error`。
- **S7 補充（同日，review 後；先紅後綠）**：
  - **真實原因**：文字未變但有 restyle／拖曳時，plan gate 先回 `no_change`（順序由 structural gates 釘住，不動 `plan.py`）。
    `edit_text` 在同意分支之前改寫：`no_change`＋`style_overrides.changed` → `style_override_present`；`no_change`＋`new_rect` →
    `geometry_override_present`；兩者皆無（真正的 no-op）→ `EditTextResult.NO_CHANGE`，零變更、不顯示拒絕通知（S7 初版會回
    REJECTED(no_change) 並跳 toast；S7 之前則是默默 legacy 重寫同樣的文字）。紅燈 5 failed（字型／字級／拖曳三個 `'no_change' ==
    'style_override_present'`／`'geometry_override_present'`、no-op `REJECTED is NO_CHANGE`、同頁移動原因碼）。
  - **沒有 View 就不是同意**：`_confirm_legacy_fallback` 在 `view is None` 時原本回 True，跨頁移動的 gate 直接呼叫它，headless
    controller 帶 `allow_rebuild` 就等於自動同意；改為回 False（紅燈 `assert True is False`）。
  - `test_text_commit_consent_flow.py` 兩個「再次 execute」測試改成先 `undo()`（真正的 redo 一定在 undo 之後）：原本在已修改的頁上
    重跑，靠的是 `no_change` → fallback；其中 `…does_not_arm_fallback_bypass…` 的 `prepare_plan` monkeypatch 打在
    `model.text_commit.plan`，engine 以名稱 import，從未生效——改打 `model.text_commit.engine`，讓強制的 `advance_mismatch`
    真的成為原因；另一個多斷言 redo 後仍為 DEGRADED_COMMITTED。沒有放寬斷言。
  - `test_legacy_kill_switch_moves_without_asking` 標為 guard（S7 前後皆綠）。紅燈後改過形狀的 fixture：段落測試改成兩行段落
    （單行時 S7 前會以 Tier 0 commit），移動測試改用單一 token 頁；兩者在 S7 前的程式碼仍會失敗（`multi_span_target`／
    `empty_replacement` → legacy → SUCCESS）。
  - 最終檢查：no_silent_legacy 29 passed；完整套件 8 批前景 **4194 passed、21 skipped、5 xfailed、0 failed**；engine 驗收 25 passed；
    umbrella 14 筆 × 8 階段全 pass（hvac-p4＋ecc-p0、hvac-p5＋p6 兩段；後一段 pytest 回報 2 passed 後行程以 127 結束，log 無錯誤，
    與先前記錄的 Qt 原生結束問題同類），missing_glyph、twins、rapid 綠，stale／IME／出廠預設仍紅；ruff、mypy、lint-imports 乾淨。
  - Pitfall 候選補充：(e) monkeypatch 必須打在使用端的名稱（`from x import f` 之後打 `x.f` 無效），否則「強制拒絕」的測試會靠別的
    原因通過；(f) 「沒有 UI 可以問」必須等於「否」，不能等於「是」。

### 2026-10-01 S9：依真正結果 finalize、view 端 token 失效、編輯綁定文件 session（critique 步驟 9＋VERIFY part 2 三項缺陷；先紅後綠）

- **(a) finalize 依真正結果**（`view/text_editing.py::finalize_text_edit_impl`）：順序改為「建 request → 在編輯框仍存在時 emit →
  立刻 pull `controller.consume_last_edit_result()` → 只有 SUCCESS 才 teardown」。`TextEditFinalizeResult.edit_result` 帶回真正結果；
  新 outcome `REFUSED`（未套用、編輯框保留）；新 reason `SESSION_SWITCH`、`SCENE_REBUILD`。**逐 reason 政策**（ui_spec §8 表＋擁有者
  2026-09-30 click-away 決定）：未套用時 APPLY／SAVE_SHORTCUT／CLICK_AWAY／FOCUS_OUTSIDE 保留編輯框與輸入（原因由 controller 的 toast
  顯示；SAVE_SHORTCUT 在沒 token 時由 view 顯示「預覽仍在更新，編輯框已保留」）；MODE_SWITCH／SESSION_SWITCH／SCENE_REBUILD 不能保留：
  有已驗證 token 就 commit，否則 teardown 並顯示「文字編輯未套用，輸入已捨棄（文件未變更）」warning（不再默默丟棄）；ESC／CANCEL／
  CLOSE_DOCUMENT 照舊捨棄。plan preview 開啟時，沒有 current token（且非拖曳／跨頁／未修改的豁免）的 finalize **不送任何 request**；
  `requires_preview_token` 由「只有 APPLY」擴大為 plan 模式下所有原地文字 commit（click-away、切模式、切 session、存檔），拖曳仍 tokenless
  （step 7 由 model 拒絕）。保留編輯框時：emit 過（controller 已結束 preview session）→ `invalidate_plan_preview(regenerate=True)` 重新
  要預覽，否則 Apply 永遠等不到 token；`finalize_text_edit` 的 `finally` 依編輯框是否仍在決定 focus guard（原本一律拆掉）；CLICK_AWAY
  以 `singleShot(0)` 把焦點還給編輯框；非 APPLY 的 reason 對「剛被拒絕的同一份輸入」不再重送（`_refused_input_key`），避免 legacy preview
  模式下 focus 變化反覆 emit＋toast。滑鼠按在編輯框外若編輯框仍在 → `event.accept()` 並 return（不在底下開新編輯框）；`create_text_editor`
  前置 finalize 後編輯框仍在 → 不疊第二個。`set_mode` 改讀 `result.edit_result`（finalize 已 pull，再 pull 只會拿到 None）。
  未提供 pull API 的 View（單元 harness）維持舊契約（emit 即 COMMITTED）；實際 app 一律 pull，未知值視為「非 SUCCESS」。
- **成功路徑同步重建 scene**：`display_page`／`initialize_continuous_placeholders`／`reset_document_view` 改用 `SCENE_REBUILD`，且在
  `scene.clear()` 前呼叫 `_detach_text_editor_before_scene_clear()`——只有「commit 正在套用中」（成功路徑的 `show_page` 重入、finalize guard
  已設）時編輯框還會在，先把 proxy／mask／focus border 移出 scene，避免被 clear 刪掉；`_teardown_editor` 另以 `shiboken6.isValid` 防已刪除
  proxy。**發現**：第一版 step-9 在單頁模式（`continuous_pages=False`）成功 Apply 時，`_refresh_undo_redo_action_state` 碰到被 clear 刪掉的
  proxy → `show_error`「already deleted」；guard 測試抓到後加上 detach。未改成 `QTimer` 延後 `show_page`（會改變大量測試的時序）。
- **(b) view 端 token 失效**：controller 的文件變更 chokepoint `_bump_render_revision`（所有 `_invalidate_active_render_state` 呼叫者）在
  active session 且編輯框開著、非 finalize 中時呼叫 `_invalidate_inline_editor_preview()` → 結束 preview session（scratch 快照也過期）＋
  `view.invalidate_text_edit_plan_preview()`（bump generation、清 token、重新要預覽）。換頁：`_on_scroll_changed` 與 `scroll_to_page` 在
  `current_page` 真的改變時呼叫 `_on_current_page_switched()`（finalize 中略過）。已知缺口：OCR 隱形文字注入不 bump render revision。
- **(c) 換 session 前 finalize＋綁定**（headline 缺陷）：新 chokepoint `PDFController._finalize_inline_editor_before_session_change()`
  （view 以 `SESSION_SWITCH` finalize，接著結束 preview session），放在 `open_pdf` 新路徑（`model.open_pdf(append=True)` 與
  `_capture_current_ui_state` 之前）、`_switch_to_session_id`（原本用 CLICK_AWAY）、`on_tab_close_requested`（關 active 分頁）、
  `detach_document_session`（原本關掉 active 分頁前完全沒 finalize）。結構性第二道防線：`EditTextRequest.session_id`／
  `MoveTextRequest.session_id`（編輯框**開啟時**以 view 既有的 `_active_document_session_id()`——浮動註解同一查法——蓋章，finalize 時
  active 可能已變），`controller.edit_text`／`move_text_across_pages` 在任何 model 呼叫前比對 active session，不同 → `REJECTED`
  （原因碼 `document_session_mismatch`，toast，零變更）；preview payload 帶 `document_session_id`，不符 → 拒絕預覽不發 token。
  `edit_text` 成功後的 `restore_viewport_anchor` timer 改成只在 session 未變時執行（避免把下一份文件捲到這份的 anchor）。
  `sig_add_textbox` 是位置參數，無法帶 session id——只靠 finalize-before-change 的順序保護（列入 concerns）。
- **(d) umbrella 加固**（皆為 **guard**：step 9 前的程式碼除了新欄位 `edit_result` 之外都會通過）：正例 Apply 另斷言 `request.requires_preview_token is True`、`_last_text_edit_finalize_result` 為 APPLY／COMMITTED／
  `edit_result is SUCCESS`；save_reopen 對**重開檔**重跑 `_trace_for`（font＝basefont、dir／size／color／opacity／type、首字 origin）並比對
  非目標 show 的 origin（排除該頁所有已 commit 的 seq）。stale 測試（換頁回來）不需改量測：實作後直接轉綠（HVAC p6 的新預覽在回來後
  1.5 s settle 內未到，Apply 維持停用）；`returned_at` 取在 settle pump 之後仍是潛在時序脆弱點（更快的機器上新 token 可能在 pump 內到達而被
  誤判 stale），未改，列入 concerns。
- **測試**（`test_scripts/test_text_commit_finalize_by_result.py`，13，全合成 Identity-H、`main.run` 真實 app、QTest 真實輸入、偏好改用
  記憶體 store 不寫使用者 recent files）：紅燈 **12 failed**（實作前）——refused Apply 關框（`None is <deleted editor>`）、click-away 無 token
  仍送 tokenless request、click-away 有 token 未帶 `requires_preview_token`、切模式／Ctrl+S 無 token 仍 commit、`edit_result` 不存在、
  toolbar 復原後 generation 未 bump（`10 > 10`）、換頁未 bump、**開啟位元組相同副本時編輯落在副本**、pending 預覽時編輯落在新文件、
  `EditTextRequest` 無 `session_id`、payload 無 `document_session_id`。一個 guard（單頁模式成功 Apply 的同步 scene 重建；step 9 前只因新欄位
  失敗），第一版 step-9 實作時抓到上述 deleted-proxy。refused-Apply 測試另加：保留的編輯框以更高 generation 重新要預覽、之後 Esc 仍捨棄（無 request、無通知、PDF 不變）。之後補 1 個：同一份被拒輸入不重送（legacy preview；step 9 前第一次拒絕就關框；突變——不記 `_refused_input_key`——轉紅 `2 == 1`）；key 含目前 token，換了文件狀態後的新 token 可再試。最終 13 passed。**突變驗證**（備份→修改→跑→還原，`cmp` 確認相同）：拿掉 `_not_applied` 的 `invalidate_plan_preview(regenerate=True)` → refused-Apply 轉紅（`8 > 8`）；拿掉 `open_pdf` 的 finalize-before-change → 副本測試只在「原文件應收到 commit」轉紅（`[] == [原文件]`），**副本仍未被改**（session 綁定單獨即可保護）；讓 `_refuse_foreign_session_request` 永遠放行 → 副本測試仍綠（chokepoint 單獨即可保護），綁定測試轉紅（`SUCCESS is REJECTED`，請求被 commit 進 B）。兩道防線各自獨立有效。
- **既有測試遷移**：`test_text_commit_no_silent_legacy::test_blank_canvas_click_away_never_reaches_legacy`（S7 釘「click-away 仍送 tokenless
  request 由 model REJECTED」→ 依擁有者決定改為「不送 request、編輯框與輸入保留」，model 端 tokenless 拒絕仍由
  `test_tokenless_commit_without_rebuild_is_refused_with_a_notice` 釘住）；`test_text_commit_degrade_visibility` 的
  `_FakeCommittedFinalizeResult` 改成在 set_mode 建構時 pull 真正（未 mock）的 `consume_last_edit_result()` 並帶 `edit_result`（模擬新
  finalize 契約，toast 仍由真實結果決定）；`test_multi_tab_plan` 19b／19j（restyle 後點外面要結束編輯框——tiered 下被拒、現在保留）改用
  S7 的 `mvc_legacy` fixture（主體是 focus／finalize 生命週期）。沒有放寬斷言。
- **umbrella**（Poppler 25.07.0，四段前景）：14 筆 × 8 階段全 pass（hvac-p4 6、p5 2、p6 2、ecc-p0 4，含新加的重開 trace／origin 與 APPLY
  斷言）；負例 missing_glyph、twins、rapid 綠，**stale-after-page-switch 由紅轉綠**；IME（環境相依）與出廠預設仍紅（非本步驟）。
- **檢查**：完整套件（268 檔，排除 umbrella 與 engine 驗收，8 批前景）**4207 passed、21 skipped、5 xfailed、0 failed**；engine 驗收 25 passed；
  ruff、mypy（55 檔）、lint-imports（4 kept）乾淨；view／controller 無 `threading.Thread`。
- **行為代價**：(1) 縮放（combo 與 Ctrl+滾輪停止後的 `_on_request_rerender` 都走 `_rebuild_continuous_scene` → `SCENE_REBUILD`）時若預覽未完成，輸入會被捨棄並提示（原本 tokenless commit）；
  (2) legacy preview（仍是出廠預設）下被拒的 click-away 會保留編輯框，使用者需 Esc 或修改後再試；(3) 同一份被拒輸入在 focus 變化時不重送，
  改內容或按 Apply 才再試。
- Pitfall 候選：(a) finalize 若先 teardown 再 emit，結果只能是「signal 有送出」——必須在編輯框存在時 emit、pull 真正結果再決定；
  (b) `controller.edit_text` 每次嘗試都結束 preview session，保留編輯框時必須重新要預覽，否則 Apply 永遠停用；
  (c) 成功路徑的同步 `show_page` 會重入 `display_page` → `scene.clear()` 刪掉仍被引用的 proxy；clear 前要把正在 commit 的編輯框移出 scene；
  (d) 換 session 的程式碼若在 finalize 之前切換 active session，未 commit 的編輯會套到新文件——plan token 由內容導出，位元組相同的副本
  擋不住；要在所有切換點之前 finalize，並把 request 綁定開啟時的 session；(e) session id 必須在編輯框**開啟時**蓋章，finalize 時再讀會讀到
  新 session；(f) 保留編輯框後 focus-out 路徑會重送同一份被拒輸入（legacy preview 沒有 token 可擋），要記住被拒的輸入；
  (g) view 已有同名方法 `_active_document_session_id()`，新增同名屬性會蓋掉它（浮動註解測試抓到）。

### 2026-10-01 S8：重建指令以 after-snapshot 重做、無反向紀錄的 Tier 0/1 重做拒絕 STALE_PLAN（critique 步驟 8；先紅後綠）

- **來源**：上一輪（04:19 因帳戶用量上限中斷）留下 `model/edit_commands.py` 的 S8 改動、新檔 `test_scripts/test_text_commit_rebuild_redo.py` 與 `test_text_commit_consent_flow.py` 兩個改寫測試；本輪逐項 review 後保留，未改產品碼。
- **行為**（`EditTextCommand`）：
  - `execute()` 以 `_executed and not _applied` 判定這是 redo，交給 `_redo()`，依第一次 execute 實際 commit 的結果分派：
    - 有 forward patch → `_redo_tier0()`（不變）；
    - outcome 是 Tier 0/1 但沒有反向紀錄 → `_refuse_redo` 回 `STALE_PLAN`：零變更、留在 redo 堆疊，不重新 prepare、不詢問、不進 legacy（ui_spec §3 情境 h）；
    - 經同意的重建（`is_real_fallback_commit`）→ `_redo_from_after_snapshot()`：還原第一次 commit 後擷取的頁面快照，並還原 protected 頁的成員關係與 `last_commit_outcome`；沒有 after-snapshot 時同樣拒絕 `STALE_PLAN`（情境 g）。
  - 只有真正的 fallback 才擷取 after-snapshot。擷取用 strict 頁級版本，因為非 strict 版本可能退回整份文件快照。`insert_pdf` 會改寫 annotation 的 `/P`，所以擷取前後要備份並還原。
  - `engine="legacy"` kill switch（chain `("legacy",)`）沒有可重播的同意，維持重跑式 redo。
  - S7 的 `_replay_confirmed_fallback`／`_fallback_ever_confirmed` 移除；`confirm_fallback` 一律是第一次決定時的 callback，每個指令最多問一次。
  - `_byte_size`／`_snapshot_chunks` 計入 after-snapshot（undo 堆疊位元組預算）。
- **跨頁移動**本來就是前後 `SnapshotCommand`（redo 還原 after bytes），不需改。
- **紅燈驗證**（不用 git checkout／stash）：gitignored 的 `build/lib/model/edit_commands.py`（01:08）與目前檔案的差異恰好就是 S8 的 hunk，內容也與 S7 紀錄一致（`_replay_confirmed_fallback`）。在 scratch 複本中只把這個檔換回 S7 版本，結果 **5 failed／12 passed**：
  - `rebuild_redo` 有 3 個失敗，都是 `AssertionError: redo re-ran model.edit_text`，分別是同意的重建 redo、after-snapshot 缺失、Tier 0 無反向紀錄；
  - `consent_flow` 的 2 個改寫測試失敗：`'EditTextCommand' object has no attribute '_after_page_snapshot_bytes'`。
- **Guard**（前後皆綠，已標註）：`test_rebuild_after_snapshot_keeps_live_annotation_parents`、`consent_flow::test_redo_does_not_reprompt_or_repeat_notice`。
- **刻意的政策改變**：`consent_flow::test_high_fidelity_commit_does_not_arm_fallback_bypass…` 原本釘「後來的 execute 仍會詢問」，現在改成「拒絕 STALE_PLAN、不詢問、零變更」，仍保證未經詢問不會 commit。其 `prepare_plan` monkeypatch 改打在 `model.text_commit.engine`。
- **真實 fixture 覆蓋**：S10 的 `test_ui_missing_glyph_rebuild_action_decline_then_accept`（HVAC p4/show11）在 36 MB 檔上以 after-snapshot 完成重建的 undo／redo，頁面串流內容逐位元組一致。
- Pitfall 候選：
  - (a) redo 不能用「沒有 forward patch」推定可以重跑，要依第一次的 outcome 分派：Tier 0/1 → 拒絕；同意的重建 → after-snapshot；只有 legacy baseline 才重跑。
  - (b) after-snapshot 必須用 strict 頁級擷取。非 strict 會退回整份文件快照，頁級還原就會套錯。

### 2026-10-01 S10：拒絕原因以白話顯示＋「改用重建文字…」（critique 步驟 10；修 B4；先紅後綠）

- **原因文案**：新增 `view/text_edit_reasons.py`（純字串，不 import model，符合 `view-no-model`）。View 與 controller 的 REJECTED toast 共用這一份對照，兩邊不會講不同的話。
  - `rejection_reason_text(code)`：
    - 缺字類（`type0_unicode_unmapped`／`type0_glyph_missing`／`type0_gid_*`／`type0_cid_out_of_map_range`／`encoding_failed`）→「原字型沒有這個字」；
    - 每個 `RejectReason`，加上 controller 自用的 `target_unresolved`、`snapshot_unavailable`、`preview_error`、`document_session_mismatch`、`cross_page_move_requires_rebuild`，都有白話句子；
    - 未知代碼 → 通用句加代碼。
  - `rebuild_offered_for(code)`：`no_change`、`document_session_mismatch`、`preview_stale`、`stale_plan`、`signed_or_widget_target`、`pending_page_maintenance` 不提供重建。
  - `effective_rejection_reason`：plan gate 先回 `no_change`（pitfall S7(c)），所以文字未變時要改寫：拖曳 → `geometry_override_present`；字型或字級 → `style_override_present`；跨頁一律 → `cross_page_move_requires_rebuild`；段落模式下 preview 的 `target_unresolved`（多行目標根本解析不到）→ `multi_span_target`（commit 端的真實原因，不再誤稱「找不到這段文字」）；真正的 no-op 不顯示。
  - REJECTED toast 改為「<白話原因>，未套用（文件未變更）」。`document_session_mismatch` 也有白話文案（S9 只有代碼）。
- **狀態**：
  - `PreviewBackedInlineTextEditor.set_plan_preview_state(generation, reason)` 與 `plan_rejection_reason()` 只記錄目前 generation 的拒絕。任何 generation bump（打字、字型或字級、拖曳、invalidate）都會讓它失效；驗證過的 plan raster 會清掉它。
  - `apply_text_edit_plan_preview` 收到 reject 時寫入這個狀態。
  - controller 新增 `_record_edit_refusal(reason)`，是所有 REJECTED 路徑的單一出口（model 拒絕、session 不符、跨頁未同意）；新增 `consume_last_edit_refusal_reason()`，與 result 一起重置。
  - finalize 先 pull 結果，再 pull 原因。`_not_applied` 要在重新要預覽（會 bump generation）**之後**，才把原因寫到新的 generation。legacy preview（仍是出廠預設）只能靠這條路取得原因。重建被拒（DECLINED）時沿用嘗試前的原因。
- **UI**（`view/pdf_view.py` 文字屬性面板，「套用」旁）：
  - `text_plan_status_label`（白話原因）與 `text_rebuild_btn`「改用重建文字…」平時隱藏；編輯框 tooltip 也帶原因。
  - `_sync_text_apply_enabled` → `_sync_text_refusal_state`，只看 live editor 目前的 generation。
  - **Apply 沒有 token 一律停用**：`apply_permitted` 拿掉 T5 對拖曳／跨頁的豁免，只剩「完全未修改」可以套用。拖曳、跨頁、改樣式、清空都只能走重建按鈕。
- **重建請求在 `view/text_editing.py` 建立**（B4）：
  - `TextEditManager.request_rebuild()` 只在 `rebuild_offered()` 時動作，所以過期或排隊中的點擊不送出。
  - 它呼叫 `finalize_text_edit(APPLY, allow_rebuild=True)`。`allow_rebuild` 是這一次呼叫的參數，不存在任何屬性上，所以同意只對該次請求有效、不會沿用。
  - 請求內容：同一個 target、text、`source_ref`、`session_id`、`target_span_id`，加上 `plan_token=None`、`requires_preview_token=False`、`allow_rebuild=True`；跨頁時送 `MoveTextRequest(allow_rebuild=True)`。
  - 之後走 controller 既有的同意對話框（預設「否」）。文案改為說明「會刪除原文字、以可用字型重新寫入，字型、字距或相鄰排版可能改變」，仍只放代碼 chain；標題改為「確認改用重建文字」。
  - **焦點**：拒絕後重新要預覽，會讓仍有焦點的按鈕短暫隱藏，焦點離開編輯情境，40 ms 後就會觸發 FOCUS_OUTSIDE finalize（測試抓到 `_last_text_edit_finalize_result` 被覆蓋）。因此按鈕處理完後，若編輯框還在，就把焦點還給它。
- **測試**：
  - `test_scripts/test_text_commit_rebuild_action.py`（13 個；合成 subset Identity-H；經 `main.run` 的真實 app；QTest 真實點擊）。
  - 紅燈 **11 failed**（實作前）：`ModuleNotFoundError: view.text_edit_reasons`、`'PDFView' object has no attribute 'text_rebuild_btn'`，以及拖曳豁免的 `text_apply_btn.isEnabled()` `True is False`。
  - 涵蓋的情境：
    - 缺字時顯示原因與按鈕；
    - 拒絕同意 → 零變更、編輯框與輸入保留、無通知；預覽回來後按鈕再出現；
    - 同意 → 一個請求、一筆 undo、一則 warning 通知、編輯框關閉；undo／redo 串流逐位元組一致，且不再詢問、不重複通知；
    - 打字或改字型立刻隱藏按鈕，過期點擊不送出；
    - 同意不沿用：拒絕後改成可 Tier 0 的文字，一般 Apply 的 `allow_rebuild` 為 False，結果 COMMITTED；
    - 改樣式、拖曳時沒有 token、Apply 停用、提供重建；拖曳經同意後成功；
    - 不可重建的原因只顯示文字、不顯示按鈕；
    - legacy preview 下 commit 被拒時提供重建；
    - review 後補 2 個：段落模式（兩行段落；紅燈 `'找不到這段文字在 PDF 中的原始內容' == '一次修改多段文字（段落）需要重建文字'`，再加 paragraph 對照後轉綠；同意後一筆 undo）；跨頁拖曳（實作後才寫：preview 回 `no_change` → 顯示跨頁原因、Apply 停用，同意後送 `MoveTextRequest(allow_rebuild=True)`、只問一次、一筆 undo、文字移到第 2 頁）。
    - review 後收緊：「每個 `RejectReason` 都有文案」原本只斷言非空（通用句永遠非空，空泛通過），改為斷言文案不含代碼本身，缺對照就會失敗。
  - 真實 fixture：umbrella 新增 `test_ui_missing_glyph_rebuild_action_decline_then_accept`（HVAC p4/show11；先拒絕、再同意；驗 undo／redo 與通知數）。此測試在實作後才寫，因為它依賴新元件，實作前必然紅。
- **原因量測**（scratch pytest plugin，未追蹤）：
  - umbrella 全程只出現 `type0_unicode_unmapped`（3 次），14 筆正例沒有任何拒絕；
  - 合成探針出現 `type0_glyph_missing`、`empty_replacement`，以及改字型、字級、拖曳時的 `no_change`；
  - 文字已改又拖曳時是 `geometry_override_present`；engine 負例是 `growth_region_not_blank`。
  - 段落模式：`target_unresolved`（已改寫為 `multi_span_target`）；跨頁拖曳：`no_change`（改寫為跨頁原因）。
  - 以上全部都有專屬文案。
- **既有測試遷移**：`no_silent_legacy::test_tokenless_commit_without_rebuild_is_refused_with_a_notice` 原本斷言 toast 含原因代碼，改為斷言含 `rejection_reason_text(代碼)`。這是刻意的文案改變，沒有放寬斷言。
- **檢查**：
  - 完整套件（270 檔，排除 umbrella 與 engine 驗收，10 批前景）：**4222 passed、21 skipped、5 xfailed、0 failed**。第 7 批回報 599 passed 後行程以 127 結束，log 無錯誤，屬已知的 Qt 原生結束問題。
  - engine 驗收 25 passed。
  - umbrella（Poppler 25.07.0，四段前景）：14 筆 × 8 階段全 pass（hvac-p4 6、p5 2、p6 2、ecc-p0 4）；負例缺字（兩個）、twins、stale、rapid 綠；IME 與出廠預設仍紅，與先前相同，非本步驟範圍。
  - ruff、mypy（55 檔）、lint-imports（4 kept）乾淨；view／controller 無 `threading.Thread`。
- **行為代價與缺口**：
  - (1) strict 模式下仍會提供重建按鈕，但 model 會回 `REJECTED_STRICT`。View 不知道 strict 設定；出廠為 strict=False。
  - (2) plan 模式下被拒的 Apply（例如 PREVIEW_STALE）會停用仍有焦點的 Apply 按鈕，同樣會把焦點推出編輯情境，觸發 FOCUS_OUTSIDE finalize（編輯框仍保留，但 finalize 結果被覆蓋）。本步驟未處理。
  - (3) `docs/ARCHITECTURE.md`、`docs/PITFALLS.md`、`TODOS.md` 依指示未改，留給步驟 16。
- Pitfall 候選：
  - (a) offscreen 下用 `QTest.keyClicks` 輸入 CJK 字元，行程會直接結束（exit 127，沒有 traceback，也沒有 faulthandler 輸出）。CJK 要用 `QInputMethodEvent` 的 commit string。
  - (b) 隱藏或停用仍有焦點的面板按鈕，會把焦點推出編輯情境，進而觸發 FOCUS_OUTSIDE finalize。
  - (c) 以 generation 為鍵的狀態，要在會 bump generation 的 re-arm **之後**寫入，否則立刻失效。
  - (d) preview 端 `no_change` 的 gate 順序會遮蔽樣式與位置的 override，View 必須與 commit 端用相同方式改寫。
  - (e) 同意必須是呼叫參數，不能放在 manager 屬性上；屬性在例外或重入時會外洩成「黏著同意」。

- **2026-10-01 UI critique 步驟 11：plan 模式不再渲染 CSS／HTML 系統字型 interim 預覽**（`view/text_editing.py`，新測試 `test_scripts/test_text_commit_plan_preview_no_css.py`，9 項）。
  - **紅燈**：真實 UI 路徑（plan 模式開編輯框、輸入）中 `PreviewRenderer.render` 的 spy 被呼叫：`['Buffer Tank', 'Buffer Tnak']`（開框時一次、輸入一次）。單元測試另因 `set_plan_preview_mode` 不存在而紅。
  - **實作**：`PreviewBackedInlineTextEditor` 新增 `set_plan_preview_mode()`／`plan_preview_mode()`／`plan_preview_pending()`。plan 模式下 `_regenerate_preview` 完全不呼叫 CSS renderer，只發 plan 請求；`_preview_image` 保留最後一張已驗證的 plan raster。`paintEvent` 在「文字等於原文」時仍畫 frozen 原始幀（不變）；plan 模式且文字已改時畫「最後已驗證幀，否則 frozen 原始幀」，並在尚無目前 generation 的已驗證 raster、也沒有拒絕原因時疊上「預覽更新中」徽章（右上）與輸入文字 chip（左下，UI 字型、不冒充 PDF 字型）。不再退回 QTextEdit 原生系統字型字形。拒絕（步驟 10 的 `set_plan_preview_state`）時徽章消失，由步驟 10 的原因訊息接手。
  - **設定時機**：`create_text_editor` 在第一次 `configure_render_context` 之前，依 `view._text_plan_preview_required`（controller `activate()` 已設）且 view 有 `sig_text_edit_plan_preview` 才開啟 plan 模式，所以連開框的初始 render 也不跑 CSS。legacy 預覽模式完全不變（只在 plan 時才呼叫 `set_plan_preview_mode`）。
  - **Guard**：`test_legacy_mode_still_renders_css`、`test_real_editor_in_legacy_mode_still_renders_css`（preview='legacy' 仍走 CSS，且無徽章）。
  - **驗證**：text_editing／preview 相關 14 檔 553 passed／6 skipped；umbrella 9 passed、2 failed，兩個都是既有紅燈且與本步驟無關（IME preedit；出廠預設 `max_tier` 0≠1、`preview` legacy≠plan，屬步驟 12／14）。IME 項目以暫時停用 plan 模式再跑確認：失敗訊息完全相同。ruff 乾淨。
  - **缺口**：(1) 旋轉頁／旋轉文字的 proxy 會把徽章與 chip 一併旋轉（疊層畫在 proxy 本地座標）；(2) 編輯框很矮時徽章與 chip 會重疊；(3) 樣式改變（字型／大小）但文字等於原文時仍畫 frozen 幀（沿用既有行為），尚未顯示更新中。
  - Pitfall 候選：(a) `QImage(…, Format_RGBA8888).fill(uint)` 的 uint 是原始位元組順序（0xAABBGGRR），不是 ARGB；要用 `Format_ARGB32` 才能以 0xAARRGGBB 填色與讀 `pixel()`。(b) 把 view 取代元件的方法掛到 fake editor 的路徑上要小心：`create_text_editor` 只在 plan 模式才呼叫 `set_plan_preview_mode`，否則既有 fake editor（`_FakePreviewBackedInlineTextEditor`）會 AttributeError。

### 2026-10-01 VERIFY S7／S9／S8＋S10／S11（獨立驗證，未改產品碼／測試）

- **結論**：沒有任何路徑在未經同意下進 legacy，沒有 commit 過期或錯目標的 token，也沒有 commit 進另一份文件；每個紅燈都 fail-closed（PDF 不被改錯）。
  但缺陷 1–3 違反 §3「拒絕、取消都保留輸入」，在修好之前不能說 UI 完成；缺陷 4 擋住步驟 12（翻預設會讓「新增文字框」壞掉，
  並出現「預覽≠套用」）；缺陷 5–7 不擋。
- **範圍**：讀 S7、S9、S8、S10、S11 的 diff（`model/pdf_text_edit.py` tiered 分支、`model/edit_commands.py` redo 分派、`controller/pdf_controller.py`
  的 session chokepoint／同意 gate／`_record_edit_refusal`、`view/text_editing.py` finalize／plan 模式、`view/pdf_view.py`），再以真實 app
  （`main.run`、QTest 真實輸入、記憶體偏好、modal 記錄並回安全預設；合成 Identity-H／subset 文件）做 38 個對抗探針（scratch，未追蹤）。
  每個探針都 spy `_apply_redact_insert`（legacy）、`add_textbox`、`PreviewRenderer.render`（CSS）、同意對話框，並比對每個 session 的內容串流。
  產品碼／測試前後 digest 相同。
- **守住的保證（全部實測）**：
  - **未經同意不進 legacy**：38 個探針 legacy 次數全為 0，同意對話框 0 次。涵蓋 plan 與出廠預設（legacy preview、`max_tier=0`）下的
    Apply、click-away、Ctrl+S、Ctrl+Enter、Enter（插入換行 → 「多行文字需要重建文字」，不送出）、切模式、切到其他 top-level 視窗（編輯框
    保留、不送出）、切分頁、關分頁、搜尋跳轉、縮放、旋轉頁、刪頁、關視窗。
  - **重建類操作在兩種設定下都只能走「改用重建文字…」**（真實滑鼠拖曳事件；其餘用 combo／按鍵）：同頁拖曳、跨頁拖曳、改字型、改字級、
    清空、段落模式，各在 plan 與出廠預設跑一次，共 12 個探針。每次都按 Apply 再 click-away。
    - 結果：legacy、同意、`add_textbox` 皆 0，串流不變，編輯框與輸入保留，重建按鈕出現，原因文案正確。
    - plan 模式：Apply 停用，0 request。
    - 出廠預設：一個 tokenless request → REJECTED → 一則 toast；click-away 不重送。
    - plan 模式改字型／字級後 CSS 仍為 0。
  - **不會 commit 過期或錯目標的 token**：
    - 旋轉頁與刪除前一頁都先使 token 失效，再以 SCENE_REBUILD 捨棄。刪頁後索引位移，重新預覽得到 `target_unresolved`，不會 commit 到別頁。
    - Save As 時預覽仍在等待：編輯框保留，存檔不含編輯；token 到達後 Apply 正確 commit。
    - 編輯框開著時把目標模式 combo 改成 paragraph：token 仍綁定開啟時的 run 目標，正確 commit。
  - **不會 commit 進另一份文件**：
    - A 與位元組相同的副本 B 都開著，從 A 以分頁列切到 B（帶 token）→ 只 commit 進 A，B 串流不變。
    - 帶 token 關閉 A 分頁 → commit 落在 A 的 doc，B 檔不變。
    - 出廠預設（無 token）下，切到副本分頁，或以 `sig_open_pdf`（最近檔案）開啟副本 → tokenless 請求帶 A 的 session_id，只 commit 進 A。
  - **plan 模式沒有 CSS**：所有 plan 模式探針 `PreviewRenderer.render` 為 0。legacy preview 照舊渲染，符合 S11 設計。
- **紅燈／缺陷（新發現；都 fail-closed，PDF 從未被改錯）**：
  1. **SCENE_REBUILD 在不清 scene 時仍丟棄輸入**（來源 **S9**：`display_page` 原本就會 finalize，S9 把 reason 改成一律關閉的 SCENE_REBUILD；
     S9 前是 tokenless commit，所以這是較輕的退化）。
     - 連續模式是唯一可用的模式（`continuous_pages` 沒有 UI 開關），它走 `update_page_in_scene`，並不清 scene。
     - 實測：搜尋結果跳轉（`sig_jump_to_result`）時，被拒（缺字）或預覽未完成的輸入被捨棄，只留一則 warning。有 token 時則直接 commit。
     - 縮放（zoom combo 125%）同樣捨棄被拒的輸入。S9 已把縮放記為代價，但當時沒寫到被拒的輸入也會一起丟。
     - **擋 UI 完成**。
  2. **關分頁按「取消」仍失去輸入**（來源：「先 finalize 再問」的順序在 HEAD 就有；**S9** 的 SESSION_SWITCH 政策把它變成捨棄）。
     - 被拒的輸入會被捨棄，即使使用者取消關閉、分頁仍開著。
     - 帶 token 時，在使用者取消前就已 commit。
     - **擋 UI 完成**。
  3. **關視窗完全不 finalize**（來源：part 3 之前就存在，`handle_app_close` 不在 diff 內）。
     - 實測：文件未修改、帶 token 時，視窗直接關閉，已驗證的輸入無聲遺失（0 request、0 通知）。
     - 實測：文件已修改時，提示「共有 1 個分頁尚未儲存」，只算已 commit 的部分。
     - 推定：「全部儲存」存的不會含編輯框內容（探針已 patch `_save_session_for_close`，實際沒有存檔）。
     - 規格 §8 要求 CLOSE_DOCUMENT「捨棄並警告」，但 `TextEditFinalizeReason.CLOSE_DOCUMENT` 沒有任何呼叫者，又屬於 `_DISCARD_REASONS`，不顯示通知。
     - **擋 UI 完成**。
  4. **plan 模式下「新增文字框」失效，且預覽≠套用**。來源有三：
     - plan preview hook 對 add_new 也會安裝，HEAD 就是如此；
     - T5／S10 的 Apply token gate；
     - S11 的 plan 模式。
     實測：
     - 空白處新增：預覽回 `target_unresolved`，面板顯示「找不到這段文字在 PDF 中的原始內容」並出現「改用重建文字…」。
       `apply_permitted` 以空原文要求 token，所以 Apply 永遠停用，按了也是 0 request。
     - **打字完全看不見**：輸入「Hello World」後，編輯框 viewport 與背景不同的像素是 0。對照組：legacy preview 下同樣操作是 344 像素。
     - 只有 click-away 能 commit（`add_textbox`）。按重建按鈕會不經同意對話框就直接 `add_textbox`：同意框 0、`add_textbox` 1，按鈕標籤與行為不符。
     - **新增框疊在既有文字「Pump Room」上並輸入「Pump Romo」**：plan preview 解析到底下的既有 run，回了**驗證過的 token**，Apply 因此啟用。
       預覽呈現的是改寫既有文字，Apply 卻是另加一個 `add_textbox`：0 個 edit request，`add_textbox` 1，原文仍在。違反 §3「預覽和套用必須是同一個結果」。
     - 出廠預設下不會發生。**擋步驟 12**。
  5. **面板殘留**（來源 S9／S10）：編輯框被 SCENE_REBUILD、SESSION_SWITCH 或 MODE_SWITCH 拆掉後，`text_plan_status_label` 與 `text_rebuild_btn`
     仍顯示上一個原因，因為 `_sync_text_property_panel_state` 只在有 live editor 時同步。點了是 no-op，屬外觀問題，不擋。
  6. **文案錯誤**（來源 S9）：legacy preview（出廠預設）下，對同一份被拒輸入按 Ctrl+S，顯示「預覽仍在更新，編輯框已保留」。
     實際原因是 `_refused_input_key` 擋下重送，並不是預覽未完成。不擋。
  7. **潛在 fail-open**（來源：part 3 之前就有）：`pdf_text_edit.edit_text` 在 `getattr(model, "text_commit_settings", None) is None` 時
     跳過 tiered 分支，直接 legacy。`PDFModel.__init__` 一律給預設值，所以生產環境到不了，只有 mock model 會走到。
     跨頁 gate 遇到 None 則是 fail-closed，兩邊不一致。不擋。
- **既有紅燈（與前輪相同，非本輪範圍）**：IME preedit（環境相依）；出廠預設 `max_tier` 0≠1、`preview` legacy≠plan（步驟 12）。
- **Umbrella**（Poppler 25.07.0，`PDF_EDITOR_PDFTOPPM` 只設在 shell；四段前景；HEAD d409c4d；PyMuPDF 1.27.1、PySide6 6.10.2）：
  - 14 筆 × 8 階段（select／input／preview／apply／undo／redo／save_reopen／second_renderer）全部 pass：
    - hvac-p4：show11、16、6、7、18、26；
    - hvac-p5：show60、58；
    - hvac-p6：show7、5；
    - ecc-p0：show31、38、57、60。
  - 負例綠：缺字拒絕、缺字重建（先拒再同意）、twins、換頁後的過期 token、快速輸入。
  - 負例紅：IME preedit、出廠預設。
- **檢查**：
  - engine 驗收 25 passed。
  - lint-imports 4 kept、0 broken；`ruff check .` 乾淨；mypy `model/ utils/` 55 檔無問題；view／controller 沒有 `threading.Thread`。
  - 完整套件（271 檔，排除 umbrella 與 engine 驗收，分 8 批前景跑）：**4233 passed、21 skipped、5 xfailed、0 failed**。
    第 6 批回報 876 passed 後以 127 結束，log 無錯誤，屬已知的 Qt 原生結束問題。
- **剩餘工作對應 critique 步驟 12–16**：
  - 步驟 12（翻預設）：出廠預設仍是紅燈。**先修缺陷 4**：add_new 不開 plan 模式、不送 plan preview，Apply 也不受 token gate 限制。
    B5 點擊延遲與 Apply rebind 延遲需要重新量測。
  - 步驟 13（存檔）：protected 頁的存檔 guard、`save` 與 `save_as` 的覆蓋、renumber 後的 undo（Q5）都還沒做。
    本輪只確認存檔不會吞掉已驗證的 commit：帶 token 按 Ctrl+S，存出的檔案含該編輯。
  - 步驟 14（第二渲染器）：只有設定 `PDF_EDITOR_PDFTOPPM` 才會綠，`shutil.which` 仍找不到。
  - 步驟 15（目視驗收：6x 裁切、與 pilot 比對、`/verify`）：還沒做。
  - 步驟 16（文件）：ARCHITECTURE、PITFALLS（S7–S11 與本輪的候選）、TODOS 都還沒做。缺陷 7 可在這一步加 guard 一併收掉。
  - **不在 12–16 內，建議新增一步「finalize 政策補完」，處理缺陷 1、2、3、5、6**：
    - 缺陷 1：連續模式的 `display_page` 改用保留類 reason，或只在真的清 scene 時才用 SCENE_REBUILD；
    - 缺陷 2：先問要不要關閉，再 finalize；
    - 缺陷 3：`handle_app_close` 以 CLOSE_DOCUMENT finalize，並在有未套用輸入時把它算進未儲存提示。
- Pitfall 候選：
  - (a) 「這次 finalize 會不會清 scene」要看實際走的分支，不能看呼叫點：同一個 `display_page` 在連續模式並不清 scene。
  - (b) 可取消的流程（關分頁、關視窗）要先確認、再 finalize。
  - (c) 新的模式旗標（plan 模式、token gate）要逐一檢查每一種 editor intent。add_new 的 plan preview 會解析到底下的既有文字，給出不屬於這次操作的 token。
  - (d) 共用的面板狀態要在 teardown 時同步，不能只在 live editor 存在時同步。

### 2026-10-01 FP：finalize 政策補完（VERIFY part 3 缺陷 1、2、3、5、6、7＋S10 疑慮；先紅後綠）

- **同一類 bug，一個政策**：凡是結束或暫停 inline 編輯的路徑，(i) 可取消的動作先確認、後 finalize；(ii) scene 沒有真的被清掉就保留編輯框與輸入；
  (iii) 已驗證或被拒絕的輸入絕不默默遺失。`view/text_editing.py` 把每個 `TextEditFinalizeReason` 明確放進三個政策集合之一
  （`_KEEP_EDITOR_REASONS`／`_DISCARD_REASONS`／新 `_CLOSE_ALWAYS_REASONS`），guard 測試要求每個 reason 恰好屬於一個集合。
- **缺陷 1**：`display_page` 只在真的清 scene 的單頁分支才以 SCENE_REBUILD finalize；連續模式（使用者唯一可達）只捲動、更新一張 pixmap，
  不再 finalize（搜尋跳轉不再捨棄、也不再同步 commit）。之後由一般 focus-out 政策處理（焦點移到結果列表：有「目前」驗證 token 才 commit，
  否則保留）。**縮放是真的清 scene**（`initialize_continuous_placeholders`）：實測 visible-render 以 `view.scale` 當 target 而幾何在 `_render_scale`，
  延後重建會讓頁面尺寸錯亂，不可行；改為縮放 chokepoint（`PDFController._release_inline_editor_for_rescale`，涵蓋 `change_scale` 與
  `_on_request_rerender`，即 wheel／combo／pinch／fit／fullscreen）＋ View `release_text_editor_for_rescale()`：新 reason VIEW_RESCALE（保留類），
  有驗證 token 就 commit（同 click-away），否則保留編輯框、還原半套用的 wheel 縮放與 combo、以 toast 說明「已取消縮放」。
- **缺陷 2**：`on_tab_close_requested` 改為先 `_confirm_close_session`、後 finalize。未套用輸入（`has_unapplied_text_edit()`，只算該編輯框所屬 session）
  算進未儲存提示；取消 → 什麼都不跑（分頁、編輯框、輸入、PDF 全不動，preview session 也不結束）；「儲存後關閉」→ CLOSE_DOCUMENT
  （commit 驗證 token；不能套用就保留編輯框、中止關閉並說明）再存檔；「放棄變更」→ 新 reason CLOSE_DISCARD（明確、經詢問的捨棄）。
  回答前 request／commit 皆 0（測試以真實 window-modal `QMessageBox.open()`＋pump 量測）。曾加「modal 開著時不做 FOCUS_OUTSIDE」guard，
  但移除它後測試仍綠（scene 的 focus item 仍是編輯框 proxy，`_is_scene_focus_within_editor()` 已擋下），量不到紅燈，故不保留。
  **關閉「非作用中」分頁**：原本一律 `_render_active_session` 重建 scene，以 SCENE_REBUILD 結束作用中的編輯框（commit token 或捨棄被拒輸入）；
  現在作用中 session 不變時只刷新分頁列（實測紅→綠，refused／token 兩種）。
- **缺陷 3**：`handle_app_close` 把編輯框的未套用輸入算成其文件的未儲存變更（孤兒編輯框——文件已關——不算），回答後才 finalize：
  「全部儲存」→ CLOSE_DOCUMENT，不能套用就 `event.ignore()` 保留視窗與輸入；「全部放棄」→ CLOSE_DISCARD。**實測**（不 patch
  `_save_session_for_close`，重開磁碟上的檔案以串流 replay）：帶 token 的乾淨文件按「全部儲存」，存出的檔案含編輯框的文字。
- **缺陷 5**：`_sync_text_property_panel_state` 一律呼叫 `_sync_text_apply_enabled()`；沒有 live editor 時隱藏拒絕原因與「改用重建文字…」並停用 Apply。
- **缺陷 6**：同一個已被拒絕的輸入不重送時，Ctrl+S 顯示「這段輸入已被拒絕（原因）」而非「預覽仍在更新」（`_kept_notice`）。
- **缺陷 7**：`PDFModel.text_commit_settings` 改為 property，setter 把 None 轉成出廠 tiered 預設（chokepoint）；`pdf_text_edit.edit_text` 亦以
  `or TextCommitSettings()` 處理沒有該屬性的 stub。None 不再 fail-open 進 legacy，與跨頁同意 gate 一致。
- **S10 疑慮（根因修）**：`_not_applied` 的保留分支對 APPLY 立即把鍵盤焦點交回（`graphics_view.setFocus` ＋ `editor.setFocus`）；被停用的 Apply
  原本把焦點推到「取消」，打字落空。測試以真實按鍵送到當下焦點元件，必須進編輯框，且最後結果仍是 APPLY／PREVIEW_STALE。
- **測試**：新檔 `test_scripts/test_text_commit_finalize_policy.py`（21 項，真實 app、真實 QTest 輸入；關閉提示以真 modal 回答，Cancel 不會
  因 `clickedButton() is None` 假通過）＋ `test_text_commit_no_silent_legacy.py::test_unknown_settings_fail_closed_like_the_cross_page_gate`。
  紅燈：首輪 17 failed／3 passed（`test_zoom_with_an_untouched_editor_still_zooms` 為標示的 guard；另兩項加強後再量）。其後加強或改寫的
  測試逐一「只反轉該修正 hunk」實測紅燈（scratch 備份＋sha256 還原比對）：APPLY 焦點 → S10 測試紅（焦點在「取消」，打字落空）；
  `display_page` → 3 個搜尋跳轉測試紅（含「點擊內同步 commit」）；先確認後 finalize → 3 個分頁測試紅（含「提示前已送出」）；
  關視窗計入未套用輸入 → 4 個視窗測試紅（含「全部放棄」無提示）；非作用中分頁 → 2 紅。綠燈：21＋1 passed，連跑穩定。
- **回歸**：全套件 8 批（排除 umbrella 與引擎驗收）4255 passed、21 skipped、5 xfailed、0 failed（= 先前 4233 ＋ 本輪 22）；umbrella 14×8 綠
  （112 phase pass），紅燈僅 IME preedit（環境）與出廠預設（步驟 12），與先前相同。`ruff check .` clean、mypy `model/ utils/` 無錯、lint-imports 4 kept。
- **刻意保留的「commit 或可見捨棄」路徑**（真的清 scene 或真的換 session，無法保留 proxy）：切分頁、undo/redo 後的 `_refresh_after_command`、
  結構操作（刪頁、旋轉、重排、插頁、合併、拉直）、浮水印增改刪、開啟另一份文件、切模式、detach 分頁。
- **Pitfall 候選**：(a) 會不會清 scene 看實際分支：`display_page` 連續模式不清，縮放（`initialize_continuous_placeholders`）會清；
  (b) 可取消流程先確認再 finalize；動作只針對「別的」文件時（關非作用中分頁）不得重建作用中 scene；
  (c) 嵌在 `QGraphicsProxyWidget` 裡的編輯框，`editor.setFocus()` 只移動 scene focus item，要先 `graphics_view.setFocus()` 才拿得到鍵盤焦點；
  (d) 關閉提示若會跳出，測試 teardown 的 `view.close()` 在 offscreen 會卡死（真 modal）；本輪以「孤兒編輯框不算」修掉一處，其餘測試以 patch
  `handle_app_close` 或回答提示處理；(e) settings 這類注入 DTO 在 chokepoint（property setter）正規化，不在每個讀取點各自猜。

### 2026-10-02 B：新增文字框不走真文字 plan 預覽／token gate，並綁定文件 session（VERIFY part 3 缺陷 4；擋步驟 12；先紅後綠）

- **根因（同一類）**：plan 模式、plan preview hook、Apply token gate、拒絕原因與「改用重建文字…」都以模式旗標（`_text_plan_preview_required`）判斷，
  沒有看 editor intent，所以 add_new（新增文字框）也被當成真文字編輯：空白處預覽回 `target_unresolved`（面板「找不到這段文字…」＋重建按鈕、
  Apply 永久停用、plan 模式不畫 CSS 所以打字看不見、重建按鈕不經同意直接 `add_textbox`）；疊在既有文字上時預覽解析到底下的 run 並給出驗證 token，
  Apply 卻是 `add_textbox`（預覽≠套用）。另外 `sig_add_textbox` 不帶 session id，只靠 finalize 順序保護。
- **修正**（`view/text_editing.py`、`view/pdf_view.py`、`controller/pdf_controller.py`）：
  - 新 chokepoint `TextEditManager._plan_preview_applies(intent=None)`：只有 `edit_existing` 且 plan 開啟才為真；這是本模組唯一讀取該旗標的地方
    （guard 測試鎖住）。`create_text_editor` 以**參數** `editor_intent` 判斷（此時 `view.editing_intent` 仍是上一個編輯框的值）；
    `apply_permitted`、`requires_preview_token` 都改走它。
  - add_new 不安裝 plan preview hook（不送任何 payload，不可能解析到底下的文字），不開 plan 模式（打字照舊以 CSS 預覽顯示——它是新文字框，
    不會讓既有文字跳字型）；`rebuild_offered()` 對 add_new 一律 False；`current_rejection_reason()` 對 add_new 只回 commit 端的拒絕原因原樣，
    不做真文字改寫。
  - `sig_add_textbox` 加第 7 個參數 session id（`Signal(int, object, str, str, int, tuple, object)`）；`PDFController.add_textbox(..., session_id=None)`
    以抽出的 `_refuse_foreign_session(session_id)`（`_refuse_foreign_session_request` 也改用它）拒絕他文件的 add：REJECTED、
    `document_session_mismatch`、零變更、toast；View 保留編輯框與輸入、顯示原因、不提供重建，同一輸入不重送。
- **稽核其他以模式旗標而非 intent 判斷的點**：`view/` 與 `controller/` 內 `_text_plan_preview_required`／`current_plan_token`／`apply_permitted`／
  `plan_preview_mode` 全部讀點已列；其餘（縮放 `release_text_editor_for_rescale`、關閉 `finalize_text_edit_for_close`、`has_unapplied_input`、
  Apply／rebuild 按鈕處理）都經 `apply_permitted`／`rebuild_offered`／`has_unapplied_input`，已依 intent 決定。Controller 端不知道 intent，
  它的 plan gate 只在 `on_text_edit_plan_preview_request`（add_new 不再送請求）。
- **測試**：新檔 `test_scripts/test_text_commit_add_text_intent.py`（9 項；真實 app `main.run`、工具列真實點「新增文字框」、真實點擊與按鍵；
  spy `PDFModel.add_textbox`）。
  - 紅燈（實作前）**6 failed／2 passed**：
    - 空白處（plan 設定）：`{'plan_preview_mode': True, 'plan_payloads': 1, 'rejection_reason': 'target_unresolved', 'status_label': '找不到這段文字在 PDF 中的原始內容',
      'rebuild_button_shown': True, 'rebuild_offered': True, 'apply_enabled': False, 'painted_text_px': False}`；
    - 改字級後仍 Apply 停用；
    - 疊在「Pump Room」上輸入「Pump Romo」：`plan_payloads 1`、`plan_token True`；
    - session 綁定 [legacy]：Apply 後 `add_textbox` 落在位元組相同的副本 `bound (1).pdf`；[plan]：Apply 停用、結果為 None；
    - guard：`_text_plan_preview_required` 在 text_editing.py 讀 4 次。
  - 3 個標示 guard（實作前即綠）：click-away 只 commit 一次；有 add 框時以真實點擊切到副本分頁 → 只落在原文件；有 add 框時以 `sig_open_pdf`（最近檔案）開啟位元組相同的副本 → 只落在原文件（`open_pdf` 先 finalize 再啟用新 session，綁定不會把它變成拒絕；實作後補寫）。
  - 綠燈：9 passed。
- **文件待更新（步驟 16，依指示本輪未改）**：`sig_add_textbox` 參數由 6 個變 7 個；`docs/ARCHITECTURE.md`（約 364、660 行）、`docs/FEATURES.md`（約 65 行）、`docs/架構.txt`（約 117 行）仍寫舊簽章。
- **回歸**：add-text／textbox／object ops／multi-tab／gui regressions／manager foundation／degrade／consent／no-silent-legacy／cross-page／interaction modes
  277 passed、1 skipped；finalize_by_result＋finalize_policy＋plan_preview_no_css＋rebuild_action＋apply_by_token＋rebuild_redo＋preview_contract＋本檔 106 passed；
  其餘 text_commit／text_edit／editor 測試 58 檔 1813 passed、6 skipped、5 xfailed。umbrella（Poppler 25.07.0，只設在 shell）14×8＝112 phase 全 pass，
  紅燈僅 IME preedit（環境）與出廠預設（步驟 12），與先前相同。`ruff check .` clean、lint-imports 4 kept。
- **未做／留給後續**：(1) `sig_add_textbox` 的字級型別仍是 `int`：實測 `emit(..., 10.5, ...)` 收到 `10`，違反「字級保持 float」，未改（另開紅燈再修）；
  (2) `derive_tier0_preview_target` 在 `original_text` 為空、無 span id／source_ref 時仍會解析矩形內任意 run（model 端潛在問題；本輪由 View 不送請求擋下）；
  (3) 步驟 12 的 B5 點擊延遲與 Apply rebind 延遲仍待重新量測。
- **Pitfall 候選**：(a) 新模式旗標要逐一對每種 editor intent 判斷，最好收斂到單一 intent-aware chokepoint 並以 guard 測試鎖住讀點數；
  (b) `create_text_editor` 在設定 `view.editing_intent` 之前就要決定 plan 模式，必須用參數而非 view 狀態；
  (c) PySide6 `Signal(int)` 收到 float 會無聲截斷（10.5→10）；(d) add 類 commit 也要帶 document session，不能只靠 finalize 順序。

### 2026-10-02 L：出廠預設翻轉＋點擊／Apply rebind 延遲修正（critique 步驟 12；先紅後綠）

- **延遲根因**：HVAC p5/p6 冷點擊、commit 後第一次點擊、T5 Apply rebind 都要重播整頁內容流；瓶頸是逐位元組 Python lexer（p5/p6 約 93 萬 token）。
  其次是 `_prove_line` 的 O(行×show) 掃描、PyMuPDF `page.annots()` 的 O(n²) 走訪，以及 `cid_fonts` 逐 glyph 解析 loca。
- **修正（只在 main thread 加速，不加 worker、不碰 B5）**：
  - `pdf_lexer.lex_content_stream(data, *, coalesce_inert=False)`：用 C 層 regex 把「重播效果只有清空 operand」的區段合成一個 `TokenKind.INERT_RUN`。
    - 頂層字母表 `mlcvyhreSsfFBbnWGgKkJiR*`，禁止 cm/gs。
    - q-block 字母表多了 `wjM`，q…Q 需平衡、最多 3 層，cm 必須有 6 個數字（反向 regex 驗證），否則整條流停用快路徑。
    - 契約：有無合併時 PageReplay 完全相同（語料等價測試＋1500 組 fuzz＋31 個對抗案例＋6 個線性時間 guard）。
  - `replay.py` 開啟合併；`source_run._OriginIndex` 用 grid／bisect 預篩，精確判斷照舊；`inspect._annotation_entries` 改走 first_annot/next 鏈，fingerprint 位元組不變；loca 改用 `struct.unpack_from`。
  - **翻轉後才暴露的第二個原因**：每頁文字索引（`ensure_page_index_built`，HVAC 約 110–125 ms）以前由段落模式的外框繪製（`_draw_all_block_outlines`）在進入編輯模式／viewport 變動時順便建好。
    run 模式下那個函式直接 return，於是索引延到第一次 hover 才建，和 source-run grouping 擠在同一個 GUI 事件。
    翻轉後重新量測：p6 冷點擊 222/294 ms、p5 191/333 ms。
    修正（view）：run 模式下外框 pass 仍為可見頁預建索引（不畫外框），換頁時（`_on_current_page_switched`）也排一次去抖動的外框 pass。
    只預建索引，不預熱 resolver。
- **量測**（5 次；中位數／最大值，ms；量測前已讓 render／thumbnail 背景工作靜止；「前」為修正前，當時索引已由 harness 切換下拉時預先建好；「後」為最終程式碼、出廠預設 run）：

  | 頁 | 冷點擊 前→後 | commit 後點擊 前→後 | Apply rebind 前→後 |
  |---|---|---|---|
  | p4 | 195/199 → 106/132 | 152/176 → 80/88 | 109/135 → 71/87 |
  | p5 | 1681/1739 → 89/118 | 1602/1693 → 64/146 | 1762/1830 → 126/140 |
  | p6 | 1661/1769 → 147/190 | 1611/1694 → 124/135 | 1676/1789 → 176/205 |

  - 單獨重播：p5 1376→30 ms，p6 1547→63 ms。
  - 進入編輯模式那個事件（預建可見頁索引）：p4 201/212、p5 211/244、p6 210/226 ms，屬閒置時段，不在點擊內。
  - 目標：點擊不阻塞 >150 ms，**p6 冷點擊未達成：最大 190 ms**（中位數 147；其中 resolver 本身 131–186 ms）；p4、p5 達成。rebind 中位數 <300 ms，三頁皆達成。
- **預設翻轉**：`TextCommitSettings` 預設改為 tiered＋`max_tier=1`＋`preview="plan"`；目標模式下拉預設改為 `"run"`。
  - 函式層預設跟著改：`TieredCommitEngine`／`open_preview_session`／`PreviewSessionInput` 的 `max_tier` 都改為 1。`plan.prepare_plan` 仍是 0，刻意不動。
  - Controller 讀不到設定時以出廠預設處理（`_text_commit_settings()`）。
  - **已儲存值的規則**：唯一的儲存處是 TEXT_COMMIT_* 環境變數，明確設定的值一律優先。`TEXT_COMMIT_MAX_TIER=0` 仍是 Tier 0，`TEXT_COMMIT_PREVIEW=legacy` 仍是 legacy 預覽，無效值退回同一預設。
  - preview 的預設跟著 engine：tiered 時為 plan，其他為 legacy。kill switch `ENGINE=legacy` 單獨設定時，仍是不需 token 的 legacy 預覽。
  - 這條規則同時放在 `from_env` 與建構子：`preview` 預設哨兵為 `"auto"`，在 `__post_init__` 解析，所以 `TextCommitSettings(engine="legacy")` 不會變成 legacy engine＋plan 預覽這種不一致組合。
  - 下拉選單不持久化，沒有已儲存值。
- **測試**：
  - 新檔 `test_text_commit_replay_fast_path.py`、`test_text_commit_click_latency.py`：含真實 app 的 HVAC p5/p6 計時；CI 安全門檻為點擊 <400 ms、rebind <600 ms。
  - 新檔 `test_text_commit_shipped_defaults.py`：`main.run`，不設任何 env，真實點擊與輸入，Apply 依 token commit，另含 kill switch guard，以及「進入編輯模式／換頁後、尚未 hover 前，可見頁索引已建好」。
  - `test_text_commit_settings.py`：新增建構子 preview 跟 engine、已儲存值不被覆寫（guard）、函式層預設跟出廠 tier。
  - `test_main_startup_behavior.py`：下拉預設改為 run。
  - umbrella 正向案例參數化為 env／shipped 兩條：shipped 這條刪掉所有 TEXT_COMMIT_*。
- **紅燈證據**：
  - 延遲：`cold click blocked the GUI thread 1639 ms`、`Apply identity rebind took 1834 ms`、`first click after the commit blocked 1525 ms`；fast-path／grouping 5 failed。
  - 預設：`assert 0 == 1`（max_tier）、`'legacy' == 'plan'`、`'paragraph' == 'run'`、umbrella `('max_tier', 0) != ('max_tier', 1)`、shipped 啟動 `('tiered', 0, 'legacy', False) != ('tiered', 1, 'plan', False)`。
  - 建構子：`TextCommitSettings(engine="legacy").preview` 為 `'plan'`。
  - 預建索引：`entering edit mode left the visible page unindexed`（`'missing' == 'clean'`）；修第一條腿後，第二條腿仍紅：`moving to page 3 left it unindexed`。
- **測試遷移**：主題是舊預設的測試改為明確固定設定，沒有放寬任何斷言。
  - 主題是 Tier 0 閘門、或 tiered 拒絕後才到達的 legacy 分支：固定 `max_tier=0`。涵蓋 tier0 planner、tier1_slice1 的 max_tier 0 那條、shadow_mode 兩項、persistence、maintenance、default_engine_ux 的 stale undo、short_term_safety 的 rollback、helpers 的 prepush growth、preview_contract 的 render rejection。
  - 主題是 legacy CSS 遮罩：`no_jump_editor_geometry` 兩項固定 `preview="legacy"`。實測 plan 模式下空字串被拒（`empty_replacement`），等 4 s 後舊字形仍 100% 可見、Apply 停用；這是 plan 預覽「不畫 CSS、只顯示驗證過的 raster」的契約，不是遮罩回歸。
  - 小數字級：改用 UI 實際傳遞的方式 `StyleOverrides(font_size=9.5)`。走 `style_override_present` → 經同意的 rebuild → 9.5。
  - 4 個 GUI helper 在點擊前讀 run 幾何：下拉預設已是 run，不再觸發建索引，所以補 `ensure_page_index_built(1)`。已實測真實點擊不需預先建索引。
- **回歸**（最終程式碼）：全套 8 批＋新檔 1 批，全部前景執行、各 <9 分鐘：4349 passed、21 skipped、5 xfailed（exit 127 為已知 Qt 原生結束）。
  - 第 03 批第一次有 1 個失敗：`test_print_subprocess_helper` 的 heartbeat 時序；該檔單獨跑 3 passed，整批重跑 322 passed。
  - umbrella（Poppler 25.07.0，只設在 shell）：env 與 shipped 兩條各 14×8＝112 phase 全 pass，共 28 列。
  - 負向案例除 IME preedit（已知的離屏環境紅燈，訊息與先前相同）外全綠，`test_shipped_text_commit_defaults_are_the_acceptance_configuration` 轉綠。
  - `ruff check .` clean、mypy `model/ utils/` 無問題、lint-imports 4 kept、`threading.Thread` grep 無結果。
- **疑慮**：
  - (1) commit 後，髒文件的 live thumbnail 在 GUI thread 重繪約 21×170 ms，量測時以靜止背景工作遮掉；既有問題，不在本步範圍。
  - (2) 背景 render 執行緒持有 GIL 時，未靜止的 app 內點擊曾卡 13 s。
  - (3) Apply 整體停頓 p5/p6 約 2–2.5 s，來自 commit＋verify，不在 rebind。
  - (4) **p6 冷點擊未達 150 ms 目標**：最大 190 ms（中位數 147），瓶頸是 resolver 本身；p5 commit 後點擊有一次 146 ms。
  - (7) 進入編輯模式那個事件會為可見頁建索引，約 200–244 ms，屬閒置時段。舊的段落預設也在同一處建索引並畫外框。
  - (8) 在 `test_files/test-complexed-layout.pdf` 第 1 頁第一個 span（`Stirling-Tools/Stirling-PDF` 改一個字），出廠預設下 plan 預覽以 `no_source_match` 拒絕，4 s 內沒有 token，Apply 停用。
    這是 run 模式的定位失敗。run 現在是下拉預設，但 umbrella 只涵蓋 HVAC／ECC；本步未追查。
  - (5) tiered 下行內編輯無法把整個 run 刪成空字串（`empty_replacement`；T16 起即如此），plan 預覽讓它更明顯；只能用「改用重建文字…」。
  - (6) `model.edit_text` 的 `size`／`font`／`color` 參數在沒有 `StyleOverrides` 時會被 tiered 引擎忽略，fallback chain 為空；UI 看不到，但直接呼叫 API 的人會踩到。
- **Pitfall 候選**：
  - (a) Python 逐位元組 lexer 是整頁重播的瓶頸；任何合併快路徑都必須以「PageReplay 相等」為契約，並有線性時間 guard（歧義的數字 regex 會指數回溯）。
  - (b) PyMuPDF `page.annots()` 是 O(n²)。
  - (c) 背景 fitz 執行緒會搶 GIL，延遲量測前要先靜止。
  - (d) `dataclasses.replace(settings, engine=...)` 會帶著已解析的 preview。
  - (e) 每頁索引預建原本是段落外框 pass 的副作用，run 模式下該 pass 直接 return。翻轉預設時要逐一找出依賴舊預設的副作用。
    同類：下拉預設已是目標值時，`setCurrentIndex` 不發信號。
  - (g) `show_page` 呼叫 `scroll_to_page(emit_viewport_changed=False)`，換頁時不會觸發 viewport 去抖動的工作，要改掛在 `_on_current_page_switched`。
  - (f) 上述 `size` 參數在 tiered 下被忽略的問題。

### 2026-10-02 VERIFY part 4：FP／B／L（獨立驗證，未改產品碼／測試）

- **結論**：在**出廠預設**（不設任何 TEXT_COMMIT_*）下，沒有任何路徑在未經同意下進 legacy（所有探針 legacy 0，唯一一次是使用者同意的重建）；
  沒有 commit 過期或錯目標的 token，也沒有 commit 進另一份文件（含新增文字框＋位元組相同副本）。FP 修好的輸入遺失路徑（搜尋跳轉、縮放、
  關分頁按取消、關視窗乾淨／髒、「全部儲存」、Ctrl+S、被拒後失焦）全部實測守住。umbrella 出廠預設 14×8 全綠。
  但新發現缺陷 1（新增文字框或同意重建後，該頁真文字編輯一律被拒到存檔並重開編輯框為止）**擋「UI 完成／出廠預設可交付」**（不擋資料安全）；p6 冷點擊仍未達 150 ms。
- **方法（確保量到的是出廠預設）**：
  - 探針（scratch `v4/p4_probe.py`，未追蹤）：`fbr._App` 以 monkeypatch proxy 把 harness 的 TEXT_COMMIT_* `setenv` 改成 `delenv`，在 `main.run` 前生效；
    每次啟動記錄 env 無 TEXT_COMMIT_*、settings＝(tiered, 1, plan)、下拉＝run。真實 QTest 點擊／按鍵、真 window-modal 提示（`fpo._Prompts`），
    spy `_apply_redact_insert`（legacy）、`add_textbox`、CSS renderer、同意框，並逐 session 比對內容串流與磁碟檔案。合成文件＋HVAC（關視窗時預覽在飛）。
  - umbrella 負例原本都以 env 覆寫啟動（`_open_case` 沒傳 `shipped`）；本輪以 scratch pytest plugin 把 `_App` 一律改成 `shipped=True` 並記錄啟動事實：
    10 次啟動（4 正向＋6 個會啟動 app 的負例）env 皆空、settings 皆 (tiered, 1, plan)、下拉皆 run。
  - 延遲：L 的 scratch `measure_latency.py` 的 shipped 參數是在 `main.run` 之後才刪 env，量到的是 env 設定；env 值現在與出廠值相同（tiered, 1, plan），
    所以 L 的數字仍是同一設定，差別只在下拉預設與索引預建的副作用。本輪改為建構時 `shipped=True` 重量。
- **實測守住（出廠預設）**：
  - 搜尋（真實輸入＋點結果列）跳轉：被拒輸入保留（FOCUS_OUTSIDE→refused，0 request）；帶 token 時在焦點移到結果列時 commit 目前 token（設計如此）。
  - 縮放：Ctrl+滾輪 ×3、縮放下拉 150%、「符合視窗」按鈕：編輯框與輸入保留、縮放還原（scale／render_scale／下拉都回 100%）、0 request。
  - 關分頁按「取消」（被拒、帶 token 各一）：提示出現時與提示下 request／commit 皆 (0, 0)，分頁、編輯框、輸入、token 都在；之後 Apply 正常 commit。
  - 關視窗：乾淨文件帶 token「全部儲存」→ CLOSE_DOCUMENT commit，磁碟檔含編輯；按「取消」→ 視窗、編輯框、token 都在；A 被拒（重建被拒）＋B 髒 →
    「全部儲存」中止，B 檔未被寫、B 仍髒；A 帶 token＋B（位元組相同副本）已有另一筆編輯 →「全部儲存」兩檔各只含自己的編輯；A 新增文字框＋B 副本 →
    只有 A 檔含新文字，B 檔位元組不變。關分頁 A「儲存後關閉」＋新增文字框 → 只落在 A。
  - Ctrl+S／另存（髒文件＋重建被拒、以及預覽拒絕兩種）：編輯框與輸入保留，存出的檔案不含未套用文字，0 request。
  - 重建被拒（commit 時 FALLBACK_DECLINED）後：真實按鍵落在編輯框；焦點移到另一個 top-level 視窗或搜尋欄都不重送、不捨棄。
  - 新增文字框（出廠預設）：空白處與疊在「Pump Room」上皆 0 plan payload、plan 模式關、畫出文字（180／164 個深色像素）、Apply 可按、`add_textbox` 恰 1 次、
    復原後文字消失；疊在既有文字上時原文保留（預覽＝套用）。新增後立即點既有文字：intent＝edit_existing、plan 模式開、輸入後尚無 token 時 `apply_permitted()` 為 False（無殘留 intent）。
  - 面板：Escape、切分頁（SESSION_SWITCH）、切模式、全螢幕後，拒絕原因與「改用重建文字…」皆隱藏；新增文字框從不顯示重建按鈕。
  - 編輯框內 Ctrl+Z 退回原文後按 Apply → NO_OP，不送出舊 token。
- **新缺陷／疑慮（都 fail-closed，PDF 從未被改錯）**：
  1. **新增文字框或同意的重建之後，同頁真文字編輯一律被拒，直到存檔並重開編輯框**。
     - 來源：既有的 Tier 0 `pending_page_maintenance` gate（S7 之前會默默走 legacy）。**不是 L 造成的退化**：以翻轉前設定（env `max_tier=0`、legacy 預覽）跑同一流程，
       Apply 一樣 REJECTED，toast「頁面仍在整理中，請稍後再試，未套用」，`pending_edits` 仍為 [0]。L 只把呈現方式從「Apply 後 toast」改成「Apply 停用＋面板原因」。
     - 實測（出廠預設）：新增「Hello」後編輯同頁「Pump Room」→ 預覽 `pending_page_maintenance`，面板「頁面仍在整理中，請稍後再試」、不提供重建、Apply 停用；
       閒置 10 s 重打仍同；**復原掉剛新增的文字框也不會解除**（undo 後 `pending_edits` 仍為 [0]，同樣被拒）；Ctrl+S 清掉 `pending_edits` 後，**已開著的編輯框仍被拒**
       （preview session 開啟時就把 pending 旗標定下）；Escape 後重開才拿到 token 並 commit。同意重建（改字級）後編輯同頁另一行同樣被拒。
     - 文案「請稍後再試」不實：等待不會解除；依程式碼（`_maybe_garbage_collect`，未實測）只有存檔或 `edit_count` 到 5 的倍數才會清。
       物件操作（移動／縮放／旋轉／刪除）也走同一 chokepoint 是依 `docs/ARCHITECTURE.md` 的 `mark_page_content_dirty` 說明推定，未實測。
     - umbrella 沒涵蓋「先新增／重建、再改同頁既有文字」。
     - **判定：擋「UI 完成／出廠預設可交付」**（與 part 3 缺陷 4 同類：常見的新增文字流程走進死路，唯一出路不可發現，文案還叫人等待）；資料安全，不擋其他項目。
  2. **plan 預覽下 Ctrl+S／另存的保留通知文案錯誤**：預覽已拒絕（缺字、頁面整理中）或重建被拒時，仍顯示「文字編輯尚未套用：預覽仍在更新…」。
     FP 的缺陷 6 修正只走 `already_refused`（legacy 預覽才會設 `_refused_input_key`）；plan 模式在 `apply_permitted()` 為 False 時一律用 `_NOT_APPLIED_KEPT_NOTICE`。不擋。
  3. **全螢幕（F5／「全螢幕」）捨棄未套用輸入**：`enter_fullscreen` 先 `cancel_interaction_for_fullscreen` → MODE_SWITCH，被拒輸入被捨棄（有 warning），帶 token 則直接 commit。
     FP 說縮放 chokepoint 涵蓋 fullscreen，但進入全螢幕在到達 `change_scale` 前就已經 finalize；FP 列的「刻意保留的 commit 或可見捨棄」也沒有列全螢幕。不擋，請擁有者決定是否比照縮放拒絕。
  4. **延遲**（見下表）：p6 冷點擊最大 217 ms（中位數 146），未達 150 ms；未靜止背景工作時更差。
  5. Ctrl+滾輪在保留編輯框時每一格都跳一則相同 warning（3 格 3 則）。不擋。
  6. 使用者可見訊息含內部代碼：同意框「原因：tier0:type0_glyph_missing → legacy」、降級 toast「…：tier0:no_change → legacy」。不擋。
  7. 新增文字框字級 10.5 → `add_textbox` 收到 10（UI 實測，B 已記錄的 `Signal(int)` 截斷）。不擋。
  8. HVAC p6 輸入後預覽仍在算時關視窗：`wait_for_done(1000)` 讓 GUI 卡約 0.9 s 才出提示；「全部儲存」以「文字編輯尚未套用，已取消關閉…」保留（未說明是預覽未完成）；token 到後再關即成功。fail-closed。
  9. 既有不一致（非本輪範圍）：關分頁「儲存後關閉」一律跳另存對話框，關視窗「全部儲存」則存回原路徑。
- **延遲（出廠預設真啟動，main thread 心跳最大間隔；5 次中位數／最大值，ms；量測前靜止背景工作，同 L 的協定）**：

  | 頁 | 冷點擊 | commit 後點擊 | Apply rebind | 進入編輯模式（GUI 阻塞） | time-to-token |
  |---|---|---|---|---|---|
  | p4 | 101／134 | 80／88 | 62／78 | 193／200 | 775／825 |
  | p5 | 88／138 | 71／127 | 133／145 | 199／216 | 1569／1659 |
  | p6 | 146／**217** | 117／130 | 153／160 | 202／260 | 1277／1329 |

  - 目標「點擊不阻塞 >150 ms」：p4、p5 達成；**p6 未達成**（L 報告最大 190，本輪最大 217，resolver 本身 211）。rebind 中位數 <300：三頁皆達成。
  - 對抗（各 4 次，分開報告）：p5 commit 後不等背景靜止就點 → 中位數 138、最大 176（>150）；p6 進入編輯模式後換頁、約 450 ms 內點擊、不靜止 → 冷點擊 201–253，
    且 **time-to-token 15.0–16.8 s**（靜止時約 1.3 s）。umbrella 每頁第一筆的 preview 階段同樣 15.6 s（p5）／16.5 s（p6）。推定原因是開檔後背景 render／縮圖工作搶 GIL
    （點擊後仍有 2–4 個背景工作在跑，屬旁證，未證實）；使用者剛開大檔就編輯時 Apply 會停用十幾秒。進入編輯模式那個事件阻塞 GUI 179–260 ms，算是 GUI thread 阻塞，不是閒置。
- **Umbrella（出廠預設，無任何覆寫；Poppler 25.07.0；PyMuPDF 1.27.1、PySide6 6.10.2）**：
  - 正向 shipped 四組 4 passed：14 筆 × 8 階段＝112／112 PASS（hvac-p4 show11／16／6／7／18／26；hvac-p5 show60／58；hvac-p6 show7／5；ecc-p0 show31／38／57／60）。
  - 負例（以 plugin 強制 shipped）：缺字拒絕、缺字重建（先拒後同意）、twins、換頁後過期 token、快速輸入、出廠預設設定檢查 6 passed；
    IME preedit 1 failed，訊息與前幾輪相同（「Apply emitted the text without the preedit…」，離屏無 input context；環境相依，未在真 IME 上確認）。
- **檢查**：引擎驗收 25 passed；lint-imports 4 kept、0 broken；`ruff check .` clean；mypy `model/ utils/` 55 檔無問題；view／controller 無 `threading.Thread`。
  完整套件（276 檔，排除 umbrella 與引擎驗收；檔案清單與批次聯集比對無遺漏、無重複；9 批前景、各 <4 分鐘）：**4324 passed、21 skipped、5 xfailed、0 failed**
  （＋引擎驗收 25＝4349，與 L 相同）。第 05、06 批在回報 passed 後以 127 結束，log 無錯誤，屬已知 Qt 原生結束問題。
- **剩餘工作對應 critique 步驟 13–16**：
  - 步驟 13（存檔）：既有測試部分涵蓋（`test_text_commit_maintenance.py` 的 save_as 尊重 protection、persistence 的增量／完整存檔、`test_watermark_save_noop.py`）；
    仍缺：`prepare_doc_for_save` tool hook 對 protected 頁的 guard、UI 端 `save` 與 `save_as` 兩條都測、renumber 後 undo（Q5）。新增輸入：缺陷 1 的解除只靠存檔，
    以及 Ctrl+S 在編輯框有未套用輸入時照樣存檔（編輯框保留、檔案不含該輸入）——是否要擋或提示，屬本步的 save guard 決策。
  - 步驟 14（第二渲染器）：`_pdftoppm()` 先讀 `PDF_EDITOR_PDFTOPPM`，否則 `shutil.which`；找不到時 `second_renderer` 判 FAIL（不是 skip）。
    實測：Poppler bin 已在使用者層級的持久 PATH（User Path 含 WinGet 的 poppler-25.07.0 bin，Machine Path 沒有）；不設 `PDF_EDITOR_PDFTOPPM` 跑
    shipped-ecc-p0，`second_renderer` 4／4 PASS（tool_versions 為 pdftoppm 25.07.0）。本機已滿足；CI 沒有 fixture，不跑這條。
  - 步驟 15（目視驗收：6x 裁切、與 pilot 比對、`/verify`）：未做。
  - 步驟 16（文件）：ARCHITECTURE（含 `sig_add_textbox` 7 參數、finalize 三政策集合、`_plan_preview_applies` chokepoint、出廠預設）、`docs/FEATURES.md`、`docs/架構.txt`、
    PITFALLS（下列候選）、TODOS 都未做。
- **刻意的「可見捨棄或 commit」路徑（給擁有者確認，非缺陷）**：切分頁、切模式、undo／redo 後 `_refresh_after_command`、結構操作（刪頁、旋轉、重排、插頁、合併、拉直）、
  浮水印增改刪、開啟另一份文件、detach 分頁——被拒或未驗證的輸入以 warning 捨棄，帶 token 則 commit。本輪另見全螢幕（缺陷 3）也屬此類但未被列入。
  kill switch `ENGINE=legacy` 不受跨頁同意 gate 限制的問題依指示未動。
- **步驟 16 的 pitfall 候選彙整（parts 1–4，已去重）**：
  - 引擎／PDF：(1) /Rotate 繼承自 /Pages 時，任一 `get_text` 會把 /Rotate 寫進 page dict；(2) 快照比對只比 stream 解碼 bytes、不比 stream 字典；
    (3) `xref_object` 與 `xref_set_key`／`update_object` 後鍵序不同，字串比對 PDF 物件會誤報；`parse_pdf_value` 不適合精確相等；
    (4) MuPDF image tile 重用：先高解析度 render／解碼後，低解析度 render 與 fresh open 不同；`get_image_info(xrefs=True)` 等會全解析度解碼；快照上 render 必須先於 extraction；
    (5) 抽出的「行」不等於 show，鏡射文字反序；未追蹤筆位的 show 可畫在行上任何位置，只查直接後繼不夠；去空白比對會放行 MuPDF 由 kern／Tc 合成的空白；
    (6) Tier 1 splice 是整個 operator，不是字串範圍；token 只是名稱，cache hit 必須在 live 頁重新綁定（cached-candidate identity）；`bind_source_text` 沒有 registry 時 CID 文字一律 `undecodable_target`；
    (7) `tobytes` 快照與原檔物件表不可直接比（object stream 被丟）；存檔 tool hook 在無事可存時仍改 live 文件（`embfile_add` 設 `/PageMode/UseAttachments`）；
    (8) redo 依第一次 outcome 分派；after-snapshot 要用 strict 頁級擷取；(9) Python 逐位元組 lexer 是整頁重播瓶頸，合併快路徑以「PageReplay 相等」為契約並有線性時間 guard；
    PyMuPDF `page.annots()` 是 O(n²)；(10) **新**：legacy 內容改寫（實測：新增文字框、同意的重建；物件操作依 ARCHITECTURE 推定）讓該頁進 `pending_page_maintenance`，同頁真文字編輯被拒到存檔；
    復原該改寫不會清；preview session 在開啟時就定下 pending 旗標，存檔後已開的編輯框仍被拒。
  - 介面／流程：(11) 同意必須是本次呼叫的參數；「缺少 callback」「沒有 UI 可問」必須等於「否」；(12) finalize 必須在編輯框存在時 emit、pull 真正結果再決定；
    `controller.edit_text` 每次嘗試都結束 preview session，保留編輯框時要重新要預覽；成功路徑的同步 `show_page` 會重入 `display_page` 刪掉 proxy；
    (13) 換 session 前先 finalize（token 由內容導出，位元組相同副本也吃得下）；add 類 commit 也要帶 session；(14) 在飛的非同步結果以 generation 判新鮮，任何改變預覽輸入的操作都要 bump，
    集中在 chokepoint；以 generation 為鍵的狀態要在 re-arm 之後寫；(15) preview 端 `no_change` gate 會遮蔽樣式／位置 override，View 改寫方式要與 commit 端一致；
    (16) 會不會清 scene 看實際分支（連續模式 `display_page` 不清、縮放會清）；可取消流程先確認再 finalize；只針對別的文件的動作不得重建作用中 scene；
    (17) 新模式旗標要逐一對每種 editor intent 判斷，收斂到單一 intent-aware chokepoint 並鎖讀點數；`create_text_editor` 決定 plan 模式時要用參數而非 view 狀態；
    (18) 共用面板狀態要在 teardown 時同步；(19) 隱藏、停用或按下停用的有焦點按鈕會把焦點交給 ClickFocus 祖先而觸發 FOCUS_OUTSIDE；proxy 內編輯框要先 `graphics_view.setFocus()`；
    (20) 在編輯中點頁碼框屬 focus-outside，會以當下 token commit；(21) 組字中按「套用」會丟 preedit（離屏才量得到）；
    (22) settings 類注入 DTO 在 chokepoint 正規化；`dataclasses.replace(settings, engine=...)` 會帶著已解析的 preview；(23) 翻預設時要找出依賴舊預設的副作用
    （段落外框 pass 順便建索引；下拉已是目標值時 `setCurrentIndex` 不發信號；`show_page` 不觸發 viewport 去抖動）；(24) PySide6 `Signal(int)` 收 float 無聲截斷；
    (25) **新**：plan 模式的保留通知要依編輯框實際狀態（已拒絕／預覽中）選文案，不能只看 `emitted`／`already_refused`；(26) **新**：全螢幕經 `set_mode("browse")`，
    是借道切模式的檢視動作，會走 MODE_SWITCH 捨棄；(27) **新**：開檔後背景工作未靜止時，HVAC time-to-token 從約 1.3 s 拉到約 16 s（推定為搶 GIL）；延遲量測先靜止背景會遮掉它。
  - 測試／harness：(28) offscreen modal 永不返回，整個 pytest 卡住；關閉提示會跳出時 teardown 的 `view.close()` 也會卡；(29) stub 一律收 `*args, **kwargs`；
    monkeypatch 要打在使用端名稱；(30) offscreen 用 `QTest.keyClicks` 輸入 CJK 會讓行程直接結束，要用 `QInputMethodEvent` commit string；
    QTest 連送 focus＋按鍵不處理事件會造成假紅燈；(31) 行為政策翻轉後依賴舊行為的測試會空泛通過，要追實際走到新分支的測試；
    (32) subprocess 擷取 pytest 輸出要 `encoding="utf-8"`；(33) `QImage(Format_RGBA8888).fill(uint)` 是位元組順序；(34) 同批 Qt 測試順序相依的原生中止；
    (35) **新**：harness 的「shipped」腿若在 `main.run` 之後才刪 env，量到的仍是 env 設定（本輪發現於 L 的 scratch 延遲 harness，umbrella 正向 shipped 腿沒有此問題；
    umbrella 負例一律以 env 啟動，沒有出廠預設的負例腿）。
- **產品碼／測試**：本輪前後 digest 相同（scratch `v4/digest_start.txt`）；只在本節追加。本節以 device-guard 的 `scan_diff`（不套 plans/ 白名單）掃過，0 筆。

### 2026-10-05 擁有者決定與 IME 實機缺陷（part 4 後；part 5 尚未開始）
- **全螢幕（F5）有未套用輸入**：比照縮放，保留編輯框與輸入，不丟棄（取代 part 4 的「丟棄並警告」）。
- **Ctrl+S 有未套用輸入**：以現狀提交，並跳出提示，且照常跳出存檔視窗。
- **`engine=legacy` 緊急開關**：跨頁移動仍要使用者同意（取消 S7「豁免」）。
- **IME 組字缺陷（實機錄影，`ecc-dwg.pdf`）**：全選後以輸入法打「專案」，畫面上現有文字不變，按 Enter 才被取代；再打「示範」同樣不顯示，不按 Enter 直接點文字框外面 commit，「示範」消失，只剩「專案」。證實離線紅燈（`test_ui_apply_during_an_ime_preedit_never_commits_the_text_without_it`）不是假象，是產品缺陷：組字中的文字無聲遺失。
  - 修法方向：先紅後綠；點外面／Apply 時先 commit 或明確處理 preedit；組字期間預覽要含 preedit 或明示。
- 以上都列入 part 5（步驟 13）前的待辦，尚未實作。
