<!-- Grok Round Brief v11 (2026-10-30, from the census batch 20261030_0007_census and two design reviews of section 3.8; owner: v11 turns the census from a coarse filter into a fine one, evenly spaced pages where the 50-page cap cannot be raised; v11 rewrites mode: census (section 3.8) to run scripts/census_show_shapes.census() under the product replay budget, fixes the wording gaps the first run showed, and bumps the revision; round 7 continues). Brief v10 was (2026-10-29, from batches 20261029_2145_r2 and 20261029_2156_r2; owner: ctrl-syn slug pin built, and a census mode added; v10 states the synthetic slug pin as enforced (synthetic_slug, ungated), adds mode: census (a read-only corpus sweep, not a case bundle), and bumps the revision; round 7). Brief v9 was (2026-10-29, from batches 20261029_1308_r2 and 20261029_1809_r2; no new owner ruling: v9 states in the text that the hvac CANARY_KSIGN site (p4 show 26) is enforced from brief_revision 8 (landed 48d0d29, superseding v8 (ao)), corrects the sh_operator_present rule to the token-aware page-level scan (the product changed in 48d0d29), and bumps the revision; round 6). Brief v8 was (2026-10-29, from batches 20261028_2228_r2 and 20261029_0000_r2; no new owner ruling: v8 states in the text that the two CANARY_KSIGN second-site checks are enforced from brief_revision 7 (landed 46732a9) and bumps the revision; round 5). Brief v7 was (2026-10-28, from batches 20261028_0432_r2 and 20261028_0442_r2; no new owner ruling: v7 folds the round-3 validator erratum and I0b S5 into the text, schema-only revision bump; round 4). Brief v6 was (2026-10-28, from batches 20261026_0948_r2 and 20261026_1050_r2; owner rulings 2026-10-28: X5 ratified, D22 resolved, false-safe owner table landed, KSIGN second site; round 3). Brief v5 was (2026-10-26, from batches 20261026_0015_r2 and 20261026_0032_r2; owner rulings 2026-10-26: single runner enforced, office-report-23p registered, F2K open). Base: brief-v4.md plus section 10. The v5 schema/validator change (brief_revision 5, code_revision.runner_sha256, RUNS.json, runner_* codes, positives-only single_family, office-report-23p manifest row) is implemented in the working tree on 2026-10-26 (test_v5_* in test_scripts/test_evidence_bundle_contract.py and test_evidence_rederive.py green); paste only after that commit lands and the tracked tree is clean again.
     Paste everything below this comment into Grok Bot. Tracked copy: plans/grok-briefs/brief-v11.md (brief-v2.md, brief-v2-pilot.md, brief-v3.md, brief-v4.md, brief-v5.md, brief-v6.md, brief-v7.md, brief-v8.md, brief-v9.md and brief-v10.md stay untouched as history). Loop plan: plans/true-text-frontier-loop.md.
     Send only when the tracked tree is clean (brief section 1 / 5.3 rule 1) and the owner has exported PDF_EDITOR_PDFTOPPM in Grok's shell (section 1 step 0), and test_files/.redaction_denylist.txt exists (section 1 denylist precondition: absent on this machine at the 1114 pilot; without it every rev >= 3 batch with hvac rows is refused batch-level denylist_missing by validate and by rederive). Fill the section 0.0 mode switch first. -->


# Grok Round Brief v11 — PDF 真文字編輯「不跳」前沿探索（第 7 輪，brief 第 11 版）
brief_revision: 11　｜　contract: `true-text-case/2`（**不變**：schema 檔名仍是 `scripts/evidence_schemas/*.v2.schema.json`，`schema_version` 仍是 `true-text-case/2`；`brief_revision` 現在是 enum [2, 3, 4, 5, 6, 7, 8, 9, 10, 11]。v3 新增的規則對 `brief_revision >= 3` 的紀錄生效，v4 新增的規則對 `brief_revision >= 4` 生效（`item_range_bounds` 另對 `brief_revision == 3` 生效），v5 新增的規則（§10）只對 `brief_revision >= 5` 的紀錄生效；rev 2／3／4 的舊批次照舊驗證、報告逐 byte 不變）　｜　HEAD：用 `git rev-parse HEAD` 自行記錄（只供參考，不可照抄）

## 0. 本輪目的與定義

### 0.0 模式開關（owner 在貼上前填一個；沒填 = `full`）
- `mode: pilot`：**只跑 R0 的三個控制組** CTRL_POS_T0、CTRL_POS_T1、CTRL_NEG（hvac page_index=4，§2.1 表的前三列），全部 kind=control、variant=`ctrl`、method_id=`M2_COMMIT`、`expected_reason` 只有 CTRL_NEG 填 `"type0_unicode_unmapped"`；不做 canary、CTRL_DET、CTRL_SYN、任何 F 類與 census；不跑 pytest。驗證器會對缺少的 R0 列記 `calibration_incomplete`（unverifiable），這是預期，不要補做。pilot 的目的是確認 bundle 在 v5 規則下能通過驗證器與 Claude 端的 rederive（預期：三案 calibration ok、沒有任何 quarantine、CTRL_POS 兩案九個 phase 全 pass——前提是 owner 已依 §1 建立 `test_files/.redaction_denylist.txt`，否則整批 `denylist_missing`、rederive 拒收，這個預期達不到）；**bundle 沒通過驗證器也是有效交付**——哪裡過不了、為什麼，寫進 README 的 `## Pilot limits`（每一條沒解掉的 violation code 一行，標明是「做不到」並說為何，或「看不懂欄位定義」並說哪一句）。其餘章節（§1 執行環境含 step 0、§4 的 M0–M2、§5、§6、§7、§8）在 pilot 模式下全部有效；填不出來的欄位寫 null（schema 允許時）並在該案 `limits[]` 說明，不得編造數值、hash、case_id。
- `mode: full`：本 brief 全文，依 §2 → §3 → §5 → §6 的順序；R0 沒通過不得開始前沿案例（§2.3）。
- `mode: census`（v10 (aw)；v11 重寫，(ay)–(be)）：**唯讀的全語料普查，不是案例批次**。只做 §3.8：掃 `test_files/` 底下所有 PDF，每檔跑 `scripts/census_show_shapes.py` 的 `census()` 並回報特徵計數；不 mutation、不 render、不登錄 case_record、不跑 pytest，R0、§2、§4、§6 的批次檔案清單都不適用；**§5 也不適用，§3.8 明文引用的定義除外**（§5.1 的 slug 規則、§5.2 的頁級 `sh` 規則、§5.4 的遮蔽與第一層掃描）；不經驗證器。批次目錄是 `_evidence_pilot/<YYYYMMDD_HHMM>_census/`（不是 `_r2`）。census 同樣是一次貼上一個模式一個戳記，做完不得自行接著跑 pilot 或 full。
- **一次貼上 = 一個模式 = 一個批次戳記（v5 (z)）**：pilot 通過後，你**不得**自行升級成 full，必須等 owner 重新貼上 `mode: full`；README 第一行寫啟動本批的貼上模式（`mode: pilot`、`mode: full` 或 `mode: census`；blocked bundle 例外：第一行照 §1 step 0 寫 `blocked: …`，模式寫第二行）；每個戳記有自己的 METHODS_AND_EVIDENCE_PLAN.md（自己的 sha）、自己的 run_pilot.py 副本與 helpers/。從你自己 workspace 重用 runner 文字沒問題；跨批次目錄讀取、import 或執行檔案不行（§7）。
- pilot 與 full 兩種模式都是同一份契約（`true-text-case/2`、`brief_revision: 11`）、同一個批次目錄規則 `_evidence_pilot/<YYYYMMDD_HHMM>_r2/`、同一個 `--self-check` 自我驗證迴圈（§6 第 8 項）、同一個 §1 step 0 Poppler gate。

### 0.1 目的與定義
- 前 14 案（HVAC 10 + ECC 4，全部 Type0 Identity-H / CIDFontType2 / 嵌入字型）已經整合進產品。在出廠預設（engine=tiered、max_tier=1、preview=plan）下，以下全部通過：engine、plan preview、apply、undo/redo、save/reopen、真實 UI umbrella。
- 這 14 案本輪只當 R0 校準控制組使用，不得當成前沿案例交件。
- 本輪只做 §3 的前沿類別，流程如下：
  1. 先用產品路徑 probe 記錄拒絕碼；
  2. 再用「一次只改一個變因」的物件層實驗，找出（或否證）能做到不跳的方法；
  3. 依 §5 證據契約交件。
- 「不跳」：以下全部不變：
  - 同一個 font resource（同 font xref）；
  - glyph 形狀與字重；
  - 水平與垂直縮放；
  - origin、baseline、旋轉、鏡射；
  - Tc、Tw、Tz、Ts；
  - 鄰字；
  - **增長區原本是空白**（變寬替換不得蓋到任何既有墨跡：鄰字、線、框、影像）。判定就是產品 `verify_tier1_commit` 在 `has_ink_growth` 時跑的三道檢查，而且一律**唯讀呼叫產品函式**取得：非空白字形計數（`count_growth_zone_glyphs`）、occupancy（drawings＋stroke 證明、images、`sh`）、raster 背景證明（區域是 `(V∖guard(T)) ∪ (halo(V)∖halo(T))`，halo 2 pt，不是光禿的 strip）；見 §5.2 growth_zone。
  只有替換字自己的形狀與自然寬度可以不同。向量字或外框字永遠不算成功。
- §5.3 的六個 status，沒有任何一個代表產品成功。產品成功的條件是：Claude Code 整合成產品測試且全綠，並由 owner 用真實 UI（含真實 IME）驗收。
- **新 operand 只能是文字**：任何 splice 的新位元組，經產品 lexer 重新 lex 後只能含 §5.2 structure 規定的 token 型態；多出任何 operator（例如 `re f`、`cm`、`gs`）一律退件。這是「不得退回 legacy redact/reinsert」的機械版。`splice_kind=canary` 只有 kind=canary 的案例可以用（驗證器交叉檢查，§5.2）。
- **你自報的數字會被重新量測**：Claude 端的 rederive 會在本機以 sha256 解析出的原檔副本上重新套用你宣告的 `changes[]` 位元組、重新算圖、重新配對字形。驗證器只做算術交叉檢查；任何數字與重新量測不符 → 該案 `quarantined: remeasure`，不計入任何類別狀態。**`advance` 物件的 `adv_old_text_space`／`adv_new_text_space` 也在重新量測之列**（H1）：rederive 用產品自己的函式在本機原檔上重算——簡單字型 `plan._advance(capability, text, show.font_size, show.char_spacing, show.word_spacing)`（→ `FontCapability.string_width`，/Widths；`fonts.py:254`），Type0 `capability.cid.advance_points(cids, show.font_size, show.char_spacing)`（/W 與 /DW；`cid_fonts.py:1029`）——用舊 operand 的 CID 與 `glyph_identity[].code_bytes_hex`（**v4／V12：`string_fragment`／`fragment_split` 的 `adv_old_text_space` 是切片 `[b0, b1)` 的 advance、`adv_new_text_space` 是 `glyph_identity[]` 各 code 的 advance，前綴與後綴都不算；§5.1「目標粒度」**），`advance_source` 也由 `capability.advance_source` 重算而不是信你寫的；任一個與紀錄差超過重算的 `advance_tolerance` → `quarantined: remeasure`。你宣告的 Δ 決定 `growth_pt`、`verify_bbox_visual`、strip 與 raster 區域族，所以它不能是自報數字；而且 `applicable=true` 時 `after_bbox_visual` 在主增長邊的延伸不得超過 `verify_bbox_visual` 的延伸 + 0.5 pt（§5.1），after 的墨跡永遠跑不出被證明空白的區域。
- **你交的 before.pdf 不是量測基準**：`candidates/<case_id>/before.pdf` 的 sha256 必須等於 `source.sha256`（寫進 `source.before_pdf_sha256`，驗證器重算檔案 sha 比對）。Claude 端的 rederive 與 replay 一律從**本機語料庫**以 `source.sha256` 解析出原檔（synthetic 則用你註明的 builder 重建並比對 content stream 位元組），從不開你的 before.pdf；被改過的 before.pdf 不會讓任何數字「被重新量測成真」，只會讓整案 `quarantined: before_pdf_mismatch`。

### 0.2 owner 決策（2026-10-24 已定，本輪生效；細節見 `plans/true-text-frontier-loop.md` Owner decisions 1–7）
1. **授權類別**：F30（F30B／F30W／F30N）、F1、F2（F2I／F2R／F2G／F2K）可做 positive／negative；**F18 拒絕**（只記 probe 碼與數量，§3.6）。
2. **X5 暫緩**：F2 從 F2I（S4a）與 F2K 起步；F2R／F2G 只量化記錄、不宣稱成功（§3.3）。**暫緩 X5 不豁免 F2R／F2G：兩者都必須登錄、實際執行並完整記錄（§3.3）；`20261024_1803_r2` 以「X5 pending owner ruling」為由不登錄、不執行 F2R／F2G，是退件形狀。**
3. **不入庫**：pilot JSON 與 INGEST 報告不 commit；專有來源的 `replacement` 字串只以 hash 進 manifest；本輪沒有 Codex 同儕（與你無關，只是說明 Claude 端流程）。
4. **真 IME 驗收由 owner 自己做**（ecc-dwg 副本），只阻擋 I0a，不影響本輪任何案例。
5. **`standard_14_table` 接受**為 F30N（未嵌入 Standard 14）的獨立腿（§3.1、§5.2 glyph_identity）。
6. **`cmap_31_reverse` 接受**為無名稱 TrueType 子集的獨立腿（§3.1、§5.2 glyph_identity）。
7. **office-report-23p 登錄**（slug + sha256、`provenance="proprietary"`、自己的 `lineage_id`、無客戶字串）已於 2026-10-26 落地：manifest `corpora` 一列，本機檔名 `test_files/office-report-23p.pdf`（runner 以這個名字找它）；v5 起可做 positive／negative，列的 `relative_path` 寫 null（§3.2、§3.3）。
8. **X5 成立（2026-10-28 裁定）**：F2R／F2G 的 run collapse 丟掉替換字**內部** pair kern，算「替換字自然寬度可不同」，即不跳。依據是 I0b S4 對 0948／1050 五個 F2R／F2G 正例的重測（鄰字 untouched 偏差 0.0、in-show 偏差 0.0、overlap 0、每個新字形 6x 墨跡 ≥ 50 px；`K_written` −28／−28／27／249.8／416.4）。方法與記錄**不變**（§3.3）；I4／I5 產品 slice 落地前兩類仍是 measurement-only、不入 manifest。
9. **D22 解除（2026-10-28 裁定）**：整個 show 為目標、宣稱 `tj_multi_item_array` 的 **census** 列與 negative 列一樣豁免 `reason_order`（Claude 端 rederive 的 `_is_whole_show_negative` 修正；0032 的 F2I p0 s6 cen1 現在 rederived）。Grok 的紀錄不用改。
10. **false-safe 歸屬表已落地**（Claude 端 `default_plan()`，依 Q2）：F30B／F30W／F30N→I1、F1→I2、F2I→I3、F2R→I4、F2G→I5、F2K→I5、F3→I6、F17→I7、F31→I8、F5→I9、OUT→I1；glyph_identity 的 false-safe 一律 I1。與 Grok 無關，只說明 Claude 端流程。

## 1. 執行環境（硬性）
- 一律從 repo 根目錄執行。直譯器一律寫成相對路徑 `.venv\Scripts\python.exe -B`（`-B` 已經不寫 bytecode；**不設定任何環境變數**，`PYTHONDONTWRITEBYTECODE` 也不設——Grok 設定的環境變數是零，§7）。
- **舊批次目錄是資料，不是程式**：`_evidence_pilot/<舊戳記>/` 裡的任何 .py、.md、.json（含 `helpers/`）都不得執行、不得 import、也不得把它的文字 pipe 進直譯器（`20261024_1803_r2` 把 `20261024_1713_r2` 的 helper 文字 pipe 進直譯器算 `code_revision`，是退件形狀，§7）；`code_revision` 由本批次 `run_pilot.py` 或本批次 `<batch>/helpers/` 裡自己寫的檔計算。
- **step 0（在算 code_revision、建批次目錄之前；Poppler gate，v3 (d)）**：先讀 shell 的 `PDF_EDITOR_PDFTOPPM`，執行 `<它> -v` 取得版本字串（進每案 `tool_versions.pdftoppm`）。變數**未設定**、指到的檔不存在、或 `-v` 失敗時：建立批次目錄，只寫三個檔——`README.md`（第一行照抄 `blocked: PDF_EDITOR_PDFTOPPM unset`，其後只記 `git rev-parse HEAD` 與時間戳，不得有其他宣稱）、由程式產生的 `PARENT_SUMMARY.json`（`cases_total=0`、`by_status` 六個 key 全 0、`calibration.status="fail"`、`controls={}`、`per_class={}`）、`DONE.json`（`case_count: 0`，`parent_summary_sha256` 照 §6 第 9 項算）——然後**停止**：不碰任何副本、不做任何 case、不寫 METHODS_AND_EVIDENCE_PLAN.md、不跑 validate。**這個 step-0 bundle 是停止訊號，不預期通過 validate**：parent schema 的 required 還有 `methods_plan_sha256`（hex64）、`calibration.attempts`／`canaries`／`growth_canary_sites`、`tool_versions`（含 `pdftoppm`）、`product_findings`、`counts_derived_from`、`product_source_changes`、`pytest_runs`、`originals_untouched`，而 step 0 不寫 METHODS_AND_EVIDENCE_PLAN.md，所以 `methods_plan_sha256` 沒有誠實的值——**不得為了過 schema 編造任何 hash 或欄位值**；寫得出的欄位（`schema`、`stamp`、`brief_revision: 5`、`code_revision`、`tool_versions` 的其餘項）照實填，填不出的省略。Claude 端只讀 README 第一行與 DONE.json 的 `case_count: 0` 就判定 blocked，不對它跑 validate／rederive。**你不得自己設定這個變數**（不得 `setx`／`$env:`、不得在 run_pilot.py 或 helper 裡寫死路徑、不得在 PATH 裡搜 pdftoppm 代替）；它由 owner 在貼上 brief 之前 export。兩次 pilot 都在未設定下跑完三案，每個正向控制組都因 render_poppler blocked 落到 insufficient_evidence、calibration 判 fail——那是沒有資訊量的交付，v3 不再允許。
- Poppler 只從 shell 的 `PDF_EDITOR_PDFTOPPM` 讀取。路徑不得寫進任何檔案；只記錄 `pdftoppm -v` 的版本字串。
- **redaction denylist 前置條件（owner，貼上前）**：驗證器第一層掃描的本機 denylist 讀自 `test_files/.redaction_denylist.txt`（`DEFAULT_DENYLIST`；`validate` 沒帶 `--denylist` 時的預設路徑）。**檔案不存在、而批次裡有任何一列 `brief_revision >= 3` 且 provenance ∉ {public, synthetic}（hvac 的三個控制組就是）→ 整批記 `denylist_missing`**：這是批次層 violation（沒有 case_id），rederive 的 `BATCH_LEVEL_CODES` 把它當 blocking，整批不進 ingest。1114 pilot 時這台機器上這個檔是**缺的**（`_evidence_pilot/INGEST/20261024_1114_r2/VALIDATION.json` 的 notes：denylist file absent），所以 owner 必須在貼上 brief 之前建立它（含客戶 denylist 條目；空檔也算存在，但第一層就掃不到任何客戶字串）。**你不得建立或修改它**（test_files/ 是 §7 禁區）；self-check 出現 `denylist_missing` 時照 §0.0 寫進 README `## Pilot limits` 一行（`denylist_missing: test_files/.redaction_denylist.txt absent on this machine; owner precondition, not fixable from the batch`），不得為了消掉它改任何東西。
- 不得 pip install，也不得修改 `.venv`。
- git 只准唯讀指令：`rev-parse`、`status --porcelain`、`diff`、`ls-files`、`check-ignore`。
- **code_revision**（v5 (x2)：先建立 `<batch>/`、把 run_pilot.py 與 helpers/ 複製進去，**第一個指令**是 `run_pilot.py --phase code_revision`（或 `<batch>/helpers/code_revision.py`），在任何副本、任何 case 之前寫出 code_revision.json；所有 case 共用同一組值。未追蹤的批次目錄不影響 `tracked_diff_empty`（`git diff HEAD` 不看 untracked）。v4 要求「建目錄之前算」與「由本批 run_pilot.py／helpers 算」互斥，0015／0032 用 inline snippet 解決，那是契約缺口，不是違規；v5 起不得再用 inline snippet）：
  - `runner_sha256`（rev ≥ 5 必填）= sha256(`<batch>/run_pilot.py` 的位元組)，runner 啟動時計算，與 PARENT_SUMMARY 及 RUNS.json 最後一項一致（§6 第 2 項）；
  - `git_head` = `git rev-parse HEAD`；
  - `tracked_diff_empty` = `git diff HEAD --binary` 輸出為空（**必須** true；不空代表產品碼被改過，整批 blocked）；
  - `dirty` = `git status --porcelain` 非空（批次目錄會讓它為 true，這是預期值）；
  - `dirty_diff_id`（**只供參考，不當 gate**）：算法與 `test_scripts/test_text_commit_ui_real_corpus.py:164-180` `_code_revision` 逐位元組相同。原碼照抄如下（`_git(*args)` 回傳該 git 指令的 stdout bytes，失敗回 None；`ROOT` 是 repo 根目錄）：
    ```python
    def _code_revision() -> dict:
        head = _git("rev-parse", "HEAD")
        status = _git("status", "--porcelain")
        diff = _git("diff", "HEAD", "--binary")
        untracked = _git("ls-files", "--others", "--exclude-standard", "-z")
        hasher = hashlib.sha256(diff or b"")
        for rel in sorted(filter(None, (untracked or b"").split(b"\0"))):
            hasher.update(b"\0untracked\0" + rel + b"\0")
            try:
                hasher.update((ROOT / rel.decode("utf-8")).read_bytes())
            except OSError:
                hasher.update(b"<unreadable>")
        return {
            "code_revision": head.decode().strip() if head else "unknown",
            "dirty": bool(status.strip()) if status is not None else None,
            "dirty_diff_id": hasher.hexdigest() if diff is not None else "unknown",
        }
    ```
    你的 `git_head` 對應上面的 `code_revision`。因為未追蹤集合含你正在寫的批次目錄，Claude 重算的值會不同；它只用來證明「同一批內所有 case 來自同一個工作樹快照」。
- 批次目錄：`_evidence_pilot/<YYYYMMDD_HHMM>_r2/`
- **helper 程式（v3 (g)）**：你為巡檢、檢查或算圖另外寫的任何 .py（run_pilot.py 以外），一律放在 `<batch>/helpers/`（例如 `_evidence_pilot/<stamp>_r2/helpers/inspect_xref.py`），與 run_pilot.py 同規則：只唯讀 import 產品模組、只開 `candidates/` 裡的副本（對原檔只准讀 bytes 算 sha256）、只寫入自己的批次目錄、不 monkeypatch、不連網。**不得**從 repo 根目錄與本批次目錄以外的任何位置（OS temp 目錄、使用者家目錄、舊批次目錄、`_evidence_pilot/INGEST/`）執行任何程式或 import 任何模組——上一輪 pilot 從 OS temp 目錄跑的唯讀巡檢 helper，在 v3 是退件形狀，不論它有沒有改任何東西。**v5 (x) 的唯一放寬**：驅動這台機器的遠端 shell 工具**自己的**指令包裝腳本與輸出擷取檔可以位於 OS temp 與使用者設定檔目錄之下，這不算從批次目錄以外執行程式；條件是每個指令的 cwd 都是 repo 根目錄、透過它只執行 `.venv\Scripts\python.exe -B <batch>\run_pilot.py` 或 `<batch>\helpers\*.py`、本節列出的唯讀 git 指令與複製檔案進批次目錄，**不得** `python -c` 或任何 inline 程式（code_revision 見上），批次內任何程式不得讀取、import 或 pipe 這些工具檔；README `## Pilot limits` 保留一行揭露（工具把包裝放在哪、批次程式沒有讀它）。巡檢與定位重查（survey、locate）一律只開 `candidates/` 下的副本（v5 (aa)；`20261026_0032_r2` 的 helpers/survey.py 把原檔 bytes 當 in-memory PDF 開啟是程序偏離）。每個 helper 的檔名都列在 `METHODS_AND_EVIDENCE_PLAN.md` 的 `## Helpers` 一節（§6 第 1 項；驗證器**沒有** helpers 規則、不比對目錄與清單——清單由 Claude 端 triage 人工對照，目錄裡多一個或少一個檔在 triage 就是退件）；`helpers/*.py` 被 git 追蹤，而驗證器對它們做的只有 §5.4 第一層掃描（`scan_redaction` rglob 批次目錄裡每個 .json／.md／.py；絕對路徑、使用者名稱、主機名）。
- 檔名規則。git 只忽略 `*.pdf`、`candidates/`、`work_copy.pdf`、`render-*.png`、`preview-*.png`：
  - PDF 一律放在 `candidates/<case_id>/`：`before.pdf`、`work_copy.pdf`、`peel-<n>.pdf`。
  - PNG 檔名一律以 `render-` 開頭，例如：
    - `render-mupdf-before-6x.png`、`render-mupdf-after-6x.png`
    - `render-poppler-before-6x.png`、`render-poppler-after-6x.png`
    - `render-mupdf-fullpage-diff-2x.png`、`render-poppler-fullpage-diff-2x.png`
    - `render-growthstrip-before-6x.png`
    - `render-reopened-2x.png`
    其他名稱的 PNG 會變成可提交檔，驗證器會整批退件。
  - **批次目錄（含 `candidates/`、`helpers/`）裡只准 .json、.md、.py、.png、.pdf 五種副檔名**：其他副檔名（.txt、.log、.csv……）→ `unexpected_file`，不在 `cases/<case_id>/` 之下時沒有歸屬的 case，rederive 整批拒收。log 一律寫成 .md（UTF-8、無 BOM、不得含絕對路徑）。
  - JSON、MD、py 會被 git 追蹤：一律遮蔽（§5.4），不得含絕對路徑、使用者名稱或主機名。**neighbours.json 不得含任何 unicode 字元欄位**（只准 §5.1 列出的數值／布林 key；`is_space` 是布林，不是文字；§5.2 neighbours）。非公開檔的 case 連 `source_decode.latin1/independent` 與 `old_operand_bytes_hex` 都只能寫 sha256（§5.4）。
  - **檔案編碼與型別（驗證器強制，不分 brief_revision）**：每個 .json／.md／.py 都是嚴格 UTF-8、**沒有 BOM**（驗證器以 `utf-8` 讀，不是 `utf-8-sig`；PowerShell 的 `>`／`Out-File` 預設寫 BOM，帶 BOM 的 JSON → `json_unparseable`）；JSON 物件沒有重複 key（`json_duplicate_key`）；非 UTF-8 或含 NUL 位元組 → `file_not_utf8`；讀不到 → `file_unreadable`；所有計數與索引欄位必須是 JSON 整數——`true`／`false`、`12.0`、`0.0` 都不是整數（`integer_expected`）。用 Python 的 `open(..., "w", encoding="utf-8")` 加 `json.dump(..., ensure_ascii=True)` 寫檔就不會踩到。
- **語言規則（§5.4 同文）：** 非公開檔（provenance ∉ {public, synthetic}）的每個 case 的**自由文字欄位**（`observation`、`hypotheses[].statement/falsification`、`next_check`、`limits[]`、`attempts[].outcome/variable_changed`、`peel_chain[].removed_feature`、`phases.*.detail`、`source.lineage_reason`、`mutation.variable_changed`）一律用英文、只含 ASCII 0x20–0x7E，沒有長度限制（`displacement`、`reproducibility` 都可以）；任何從文件取出的字串（解碼後的文字、Producer/Creator、wrapper props 值、StructElem 文字、人名、機構名）**不得**出現在任何自由文字欄位，只能進 §5.4 的資料欄位並照規則遮蔽。公開檔與 synthetic 的 case 可用中文。驗證器對自由文字只做 denylist 逐字比對與 device-guard 樣式（不做長度或 CJK 啟發式）；非公開 case 的自由文字出現 CJK 只記 `redaction.scan.language_warnings`，不退件，但 Claude 端 triage 會逐條看。

## 2. R0 校準（第一步；沒通過不得開始前沿案例）

### 2.1 控制組

| class_id | 來源與目標 | 動作 | 必須觀察到 |
|---|---|---|---|
| CTRL_POS_T0 | hvac（slug=hvac，**`provenance="proprietary"`**、`relative_path=null`，sha256=9da93de982145c46af0d34a978b4bbaa1167f0937327dedb44ecad4d50fca0a2；它以這個 sha 登錄在 acceptance `CORPORA`（manifest `corpora` 只登錄四個 local_unrecorded 檔，hvac／ecc 不在其中），寫成 `local_unrecorded` 會被 rederive 整案 `quarantined: provenance_unverified`——兩次 pilot 的三個控制組都是這樣被隔離的，§3.0 (c)）page_index=4，show_seq=11 | replacement=「空調冰水管線系統圖(4)」，產品 prepare 再 commit | PREPARED Tier 0；九個 phase 全 pass（等寬；Tier 0 的 product commit 一律 `growth_zone.applicable=false`、`K_*` 全 null，§5.1）。**Tier 0 的 `probe.max_tier_1.prepared.source_advance`／`replacement_advance` 是 0.0**（`PreparedEdit` 的 dataclass 預設值，`plan.py:165-166`；`_build_tier0` 不填它們，只有 `_build_tier1` 會填）：`prepared.*` 照抄 0.0，`advance.adv_old_text_space`／`adv_new_text_space` 則用 `capability.cid.advance_points(...)` 實測（hvac p4 s11 兩者相等，Δ=0），不得把 0.0 抄進 `adv_*`，也不得把實測值回填 `prepared.*`（§5.1 (b)：等式只對 Tier 1 檢查）。`new_operand_bytes_hex` 是 **string token `<CID…>` 的位元組，不含 ` Tj`**：產品 Tier 0 只 splice string operand（`prepared.replacement.start/end` = `show.string_start/string_end`，`_build_tier0` `plan.py:2304-2308`；`replacement_bytes = encode_hex_string(...)` :2315-2319；hvac p4 s11 實測 string_end 2935、op_end 2937），`splice_kind=string_token` 的文法恰好一個 string token，多一個 `Tj` operator 就整案退件（§5.2）。Type0 hex payload = CID，§5.4 只檢查 CID 綁定，不把 token 文字當文字掃 |
| CTRL_POS_T1 | 同一檔 page_index=4，show_seq=26 | 「Drawing List」→「Drawing Title」 | Tier 1；`K_written` = 333.0（\|差\| ≤ 1e-6；`K_sum`=0.0，`K_disp_engine`=333.0）；九個 phase 全 pass，而且 **`growth_zone.applicable=true`**、`before_glyph_bboxes_intersecting=0`、`before_drawings_not_provably_clear=0`（頁框 stroke 的 bbox 會與 strip 相交，`before_drawings_intersecting_bbox ≥ 1` 是預期值，必須靠 §5.2 的 stroke 證明判清）、`before_images_intersecting=0`、`raster_proof="pass"`（`probe_regions_failed=0`；此列是產品綠燈的歷史案例，產品自己的 raster 證明在這裡通過）。`advance.Tfs`=132.01（Tf operand）、`Th`=`show.hscale/100`（Tz 79.9805）、`target.trm_scale`=0.060（= `math.hypot(linear[0], linear[1])`，`linear = transforms.combined_linear(show.tm, show.ctm)` = (0, −0.06, 0.06, 0)——產品 `_grown_verify_bbox` 的 baseline-row norm，`plan.py:2384-2385`；**不是** `hypot(*linear)` = 0.0849，那是四分量的 Frobenius norm，會把 `growth_pt` 算成 2.983 pt 而退掉這一列）、`target.user_unit`=1.0；`growth_pt` = 43.959·0.799805·0.060·1.0 = 2.1095 pt，與產品 `prepared.verify_bbox_page` 的延伸 2.10956 pt 差 2.4e-5（Basis (9)）；`advance.adv_old_text_space`／`adv_new_text_space` 必須等於 `probe.max_tier_1.prepared.source_advance`／`replacement_advance`（產品以 `advance_points` 從 /W 算出，Δ = 43.959；rederive 以同一函式重算，H1）；`target.after_bbox_visual` 在 `direction` 側的延伸不得超過 `verify_bbox_visual` 的延伸 + 0.5 pt（§5.1；texttrace 的字形框是 advance 框，Basis (11)，所以 after 的延伸就是 Δ·Th·trm_scale·user_unit，與 `growth_pt` 只差浮點雜訊）；`target.verify_bbox_visual` 與 `growth_zone.background_bbox_visual` **照抄** `prepared.verify_bbox_page`／`prepared.background_bbox_page`（驗證器以 1e-3 對公式重算，float32 往返差 2.4e-5 是預期值，§5.2）；`new_operand_bytes_hex` 是 `[<CID…> 333.000000] TJ` 的位元組（Tier 1 換掉整個 operator，`prepared.replacement.start/end` = `op_start/op_end`；Tier 0 則只有 string token，見 CTRL_POS_T0） |
| CTRL_NEG | 同一檔 page_index=4，show_seq=11 | replacement=「空調冰水管路系統圖(1)」 | `probe.max_tier_1.result="rejected"`，reason 必須恰好是 `type0_unicode_unmapped`，`detail` 照抄產品字面值 "no CID maps to a replacement character"（`cid_fonts.py:959-962`；§5.4 的 ASCII 規則放行，它不會被當成客戶字串）；頁面 content streams 位元組不變；status 依 §5.3 = probe_rejected（kind=control 且 mutation=null 不適用規則 4，直接走規則 7）；**v3 null 形式（§5.1 (f)）**：`target.replacement_provenance="unmappable"`（替換字含該字型畫不出來的「路」，依構造就是它），neighbours 的十個 post-mutation 計數器（`glyphs_checked`、`unpaired_glyphs`、`target_glyphs_after`、`target_origin_delta_pt`、`untouched_max_origin_delta_pt`、`inshow_successor_max_origin_delta_pt`、`gid_mismatches`、`ink_mismatches`、`overlap_glyphs`、`halo_shadowed_glyphs`）**全部 null**——寫 0 是「檢查過、沒有不符」的自撰宣稱，兩次 pilot 都是這樣寫的，v3 退件；`glyphs_total`、`target_glyphs_before`、`pairing_rule`、`records_file` 照填（before 側量得到） |
| CTRL_DET | CTRL_POS_T0 的 before.pdf | MuPDF 2x 與 6x 各算圖兩次（第二次 `get_pixmap` 之前先 `fitz.TOOLS.store_shrink(100)`，§5.2 render 的 store 規則 (e)；不清 store 的第二次算圖不算 CTRL_DET），Poppler 144 dpi 兩次，texttrace 兩次 | 像素差 = 0；origin 差 = 0.0 |
| CTRL_SYN_T0 / CTRL_SYN_T1 | `test_scripts.type0_fixture_builder.build_identity_h_fixture(CJK_TEXT, rotate=270, tail_text=TAIL_TEXT)` 存成 `candidates/CTRL_SYN/before.pdf`（provenance=`synthetic`，relative_path=null；只 import，不修改；`rotate=270` 讓合成頁也是旋轉頁，`tail_text` 提供同列鄰字） | 分別用 `REPLACEMENT_EQUAL_ADVANCE` 與 `REPLACEMENT_LONGER` | **T0**：PREPARED Tier 0 再 commit，九個 phase 全 pass，`growth_zone.applicable=false`（等寬，after bbox == before bbox）。**T1**：產品在 **PREPARE** 就拒絕（prepare 在 scratch 文件上證明，`engine.py:213`）：`probe.max_tier_1.result="rejected"`、reason `growth_region_not_blank`、detail 以 `glyphs:` 開頭（"glyphs: 1 character(s) already occupy the growth zone"）；`probe.max_tier_0.result="rejected"`、reason `advance_mismatch`；`probe.commit.attempted=false`；`mutation=null`，所以沒有 `advance` 物件，growth_zone phase 記 `not_run`、detail "no mutation"（§5.2；適用性規則跳過），status 依 §5.3 走規則 7 = probe_rejected（kind=control 且 mutation=null 不適用規則 4）。`tail_text` 的第一個字形緊接在目標 advance 末端，所以產品的 glyph gate 必然擋下它——這正是 CANARY_GROWTH 主站點的幾何，增長幾何的證明在那裡做（kind=canary、path=experiment，有 `advance` 物件）。兩列的 `source.synthetic_builder` 必須是 `{"callable": "test_scripts.type0_fixture_builder.build_identity_h_fixture", "kwargs": {"text": "你好世界", "rotate": 270, "tail_text": "後綴"}}`（§5.1；rederive 只 import 這個白名單 callable 重建）。**合成 before.pdf 的 sha256 每次建檔都不同**（PyMuPDF `tobytes()`／save 寫入隨機 trailer `/ID`：`JM_ensure_identity`／`fz_memrnd2`；builder 本身不用時間或亂數），所以 CTRL_SYN_* 與 CANARY_GROWTH@ctrl-syn 的 `case_id` sha8 與 `cases/`、`candidates/` 目錄名每次嘗試、每個批次都會變——良性：rederive 以 content-stream 位元組（不是檔案 sha）核對合成列，`emit_rows` 跳過合成列，不會隔離；跨批次的穩定鍵是 `join_key` `ctrl-syn/p0/show0`。不要把它列進 README `## Pilot limits` |

這三個控制組的 original/replacement 字串（共五個：acc:71 的兩個、acc:93-94 的兩個、acc:486 的一個）已經以明文存在於 `test_scripts/test_text_commit_real_corpus_acceptance.py`（`HVAC.cases`），所以是 §5.4 **第二層掃描**的**唯一例外**（calibration-row exemption：驗證器以**字串字面值**白名單放行這五個字串，`CALIBRATION_STRINGS`，不是以行號），而且只在 class_id ∈ {CTRL_POS_T0, CTRL_POS_T1, CTRL_NEG} 與以 CTRL_POS_T0／T1 為基底的六個 canary（CANARY_KSIGN、CANARY_TC、CANARY_FONT、CANARY_UNSAVED、CANARY_WRONGGLYPH、CANARY_INK；§2.2 的「基底」欄；`CALIBRATION_CLASSES`）的紀錄裡。**它只豁免掃描，不豁免 null 規則**：§5.1「非公開檔 `corpus_case.original` 必須為 null」（`redaction_null_required`，不分 brief_revision、不分 class_id）對這三列與六個 canary**照樣生效**——hvac 列的 `corpus_case.original` 一律寫 null，`original_sha256` 必填且必須是該明文 UTF-8 的 sha256（自己對該明文 UTF-8 算完整 64 位 hex，不得抄任何別處的 sha）；寫明文會被 `redaction_null_required` 整案退件，第二層白名單在那之前根本不會被問到。豁免真正用到的欄位是 `extraction.after_text_at_target`、`glyph_identity[].char` 與 `corpus_case.replacement`——canary 的 `extraction.after_text_at_target` 依設計就是原字串或替換字串（CANARY_UNSAVED 的 after.pdf 沒收到 commit、CANARY_WRONGGLYPH 畫回「1」），那不是客戶字串外洩。CANARY_GROWTH 的兩個站點（CTRL_SYN_T1、hvac p4 s161）不帶校準字串，不在豁免內。

HVAC 第 4 頁是 /Rotate 270。texttrace 一律在量測副本 `fitz.open("pdf", doc.tobytes(encryption=fitz.PDF_ENCRYPT_KEEP))` 上取，不得在受測 handle 上呼叫。產品自己的 `capture_page_state` 會在 commit 時碰 live page（`page.annots()`、`get_pixmap`、rawdict），在 /Rotate 頁會讓 /Page 物件被標 dirty、saveIncr 後 key 順序改變——這是**預期**現象，§5.2 structure 的 reopened 比較規則已經容納它，你不得因此放寬任何其他檢查。

**座標系（硬性）：** `page.get_texttrace()`、`page.get_drawings()`、`page.get_image_rects(xref)` 回傳的都是**未旋轉的 page space**（產品稱 dict space），`page.rect` 與 `get_pixmap` 是**視覺空間**。轉換一律用產品的 frame：`frame = model.text_commit.transforms.page_visual_frame_or_none(page)`（None → 該案 `page_geometry_unsupported`，記 blocked），視覺 = raw × `frame.quarter_turn`；raw = 視覺 × `~frame.quarter_turn`（產品 `_visual_bbox_to_dict_space`，`verify.py:247-268`）。在 hvac 與 fixture 上它等於 `page.rotation_matrix`，但 /UserUnit ≠ 1 或 CropBox 偏移的頁不等，**不得**用 `page.rotation_matrix` 或 `page.derotation_matrix` 代替。§5.2 每個 rect 欄位都寫明它在哪個空間；混用就是整案退件。

### 2.2 Canary（證明你的檢查器「會失敗」）
每個 canary 都在副本上做。只有 must_fail_phases 列出的 phase **全部** fail，才算「抓到」；其他 phase 額外 fail 不影響判定。growth_zone 與 neighbours 的 FAIL 規則對 kind=canary **同樣生效**（§5.2），所以 canary 可以、也必須被它們抓到。

| canary | 基底 | 突變（只改這一處） | must_fail_phases |
|---|---|---|---|
| CANARY_KSIGN（hvac 站點；位置固定在 CTRL_POS_T1 的 `page_index` 4、`show_seq` 26，`brief_revision >= 8` 的非 synthetic hvac 列由驗證器強制，否則 `ksign_canary_site`，§14 (ar)） | CTRL_POS_T1 commit 後的 stream | 把 TJ 尾端 K token 的正負號反過來（位元組 splice） | structure（K 重算） |
| CANARY_KSIGN（synthetic 站點；v6 起**必做**；v7 起驗證器承認這一列，§11 (ah)，並對 `brief_revision >= 7` 的紀錄與批次**強制檢查**兩件事，§13 (am)：這一列的 `synthetic_builder.kwargs` 必須逐字等於 CTRL_SYN_T1 的固定值（`{"text": "你好世界", "rotate": 270, "tail_text": "後綴"}`），否則 `synthetic_pin_mismatch`；批次必須同時有這一列與 hvac 站點的 CANARY_KSIGN 列（hvac 在場時），缺哪一列都是 `calibration_incomplete`。與 hvac 站點並列兩列，parent calibration 照 CANARY_GROWTH 兩站點的現行寫法） | CTRL_SYN_T1 的 before.pdf（`build_identity_h_fixture(CJK_TEXT, rotate=270, tail_text=TAIL_TEXT)` 的副本），用**產品路徑**把 `CJK_TEXT` 換成 `type0_fixture_builder.REPLACEMENT_SHORTER`（2 字）：產品在 max_tier=1 會 prepared 並 commit **Tier 1**，寫出 `[(new) K] TJ`、K ≈ −2000（HEAD df3ec65 實測，rotate 270 與 0 皆同；max_tier=0 是 `advance_mismatch`）。tail show 共用這個 pen，所以 K 補償讓 tail 留在原位 | 把那個 K token 的正負號反過來（位元組 splice，只改這一處）。hvac p4 s26 是獨立 Tm 的 Tj、後面 188 個 show 沒有一個共用它的 pen，翻號後只有 structure 看得到；這個站點翻號後 tail 整段位移 2·|K|·Tfs/1000 | structure（K 重算）。neighbours **預期同時 fail**（tail 的 `untouched_max_origin_delta_pt` > 0），但不列入 must_fail（驗證器對 CANARY_KSIGN 的 must_fail 仍只有 structure）；Claude 端 rederive 以同一條鄰字腿覆核 |
| CANARY_TC | CTRL_POS_T0 | 在目標 show 前插入 `0.25 Tc`，show 後還原原本的 Tc 值 | structure（text_state；同時 operator_count 不等） |
| CANARY_FONT | CTRL_POS_T0（字型 C2_1） | 在目標 show 前插入 `/C2_0 <原 size> Tf`，show 後還原原 Tf。**必記（hvac 上必然出現）**：換成 C2_0 後 texttrace 的 `after_bbox_visual` 比 `target_bbox_visual` 在主邊寬出約 6.1 pt（advance 用目標字型 /W 量仍相等、`displacement_ink=0`、`growth_zone.applicable=false`），growth_zone phase 記 **fail**、detail 寫出主邊延伸量（pt）（§5.2 growth_zone；`brief_revision >= 3` 下這不是退件，§8 (n)） | structure（font reuse）與 glyph_identity（growth_zone 的 fail 額外出現，不影響「抓到」） |
| CANARY_UNSAVED | CTRL_POS_T0 | 在 handle A 上 commit；after.pdf 改由 handle B 存檔。B 必須在 commit 前就開啟同一個副本，而且從未收到這次 commit。Claude 端的 rederive **不重放**這個 canary（`replay_experiment` 對它記 `skipped: canary_unsaved_handle_fault`，不是 `quarantined: remeasure`）：它的 `changes[]` 描述 A 上的 commit，`output_sha256`／extraction／save_reopen 描述 B 存出的檔，重放只會重現 commit 而不是這個錯誤；校準直接讀紀錄，canary 的證據就是 handle 紀律本身 | save_reopen 與 extraction |
| CANARY_WRONGGLYPH | CTRL_POS_T0 commit 後 | 把替換字「4」的 2-byte CID 換成「1」的 CID。「1」的 CID **從 before.pdf 同一 show 的原 operand 取**（原文「…圖(1)」畫過它，所以子集裡有），不是從 commit 後的 show 取（commit 後已沒有「1」） | glyph_identity 與 extraction |
| CANARY_INK | CTRL_POS_T0 commit 後 | 在 stream 尾端加上 `q 0 0 0 rg x y 1 1 re f Q`，蓋在 halo 外最近一個非目標字形的中心 | render_mupdf、render_poppler、neighbours（同時 structure 的 operator_count 不等） |
| CANARY_GROWTH（主站點） | `CTRL_SYN_T1` 的 before.pdf（`build_identity_h_fixture(CJK_TEXT, rotate=270, tail_text=TAIL_TEXT)`；**旋轉頁**） | 用產品路徑以外的 `E_KERN`（`[(new) K] TJ`，K 為正，鄰字位置不動）寫入 `REPLACEMENT_LONGER`。`tail_text` 的第一個字形緊接在目標 advance 末端（`type0_fixture_builder.py:142-143`），所以多出的 1 em（12 pt）**必然**蓋到它（產品自己在同一幾何上於 PREPARE 就以 `growth_region_not_blank` "glyphs: 1 …" 拒絕 CTRL_SYN_T1；這個 canary 是該拒絕的實驗路徑孿生，`before_glyph_bboxes_intersecting` 必須也是 1）：`target.after_bbox_raw` 必須與至少一個非目標、`is_space=false` 的字形 `bbox_before` 相交 | growth_zone（`before_glyph_bboxes_intersecting ≥ 1`）與 neighbours（`overlap_glyphs ≥ 1`） |
| CANARY_GROWTH（hvac 站點；有 hvac 時必做） | hvac page_index=4（/Rotate 270），**show_seq=161**（替代：show_seq=162）：Tj、Type0 `C2_2`、4 個 code unit、Tf operand 97.023（Tz 100、Tm×CTM scale 0.060 → 有效字高 5.82 pt；`advance.Tfs` 與 `K_disp_hand` 一律用 Tf operand 97.023，不是 5.82），同列右側 1.67 pt 就是下一個非空白字形（屬 show 159／160）。**不得用 show 26**：它右側第一個同列字形在視覺 x 383.94，要增長 ≥ 145.57 pt（show 26 的 Tf operand 132.01 × Tz 79.98 % × scale 0.060 = 6.33 pt 視覺 advance／em，即 ≥ 23 em）才碰得到；也不得用 show 185／186（右鄰是空白字形，`is_space=true` 不計） | 用 `E_KERN` 在尾端加一個該字型已畫過的字（1 em = 5.82 pt > 1.67 pt）；`target.after_bbox_raw` 必須與至少一個非目標、`is_space=false` 的字形 `bbox_before` 相交 | growth_zone（`before_glyph_bboxes_intersecting ≥ 1`）與 neighbours（`overlap_glyphs ≥ 1`） |

CANARY_GROWTH 同時校準座標系：strip 在視覉空間算、再轉成 `region_dict` 與 raw texttrace/drawings 相交（§5.2）。若你把 `region_visual` 直接拿去和 raw rect 相交，在 /Rotate 270 頁會落到不相干的區域而「沒抓到」——那就是 R0 不符，照 §2.3 處理。 兩個站點的 `caught` 都要為 true；`check_calibration` 會逐腿回報哪一腿沒抓到（`geometry_overlap`＝after bbox 是否真的與非空白鄰字 bbox 相交、`growth_zone_glyph`、`growth_zone_raster`、`neighbours_overlap`），讓「幾何沒碰到」與「檢查器有 bug」分得開。

### 2.3 校準規則
- R0 任一項不符時：
  - 只准修改你自己的 `run_pilot.py` 檢查程式，不得放寬任何數字；
  - 整個 R0 重跑，最多 3 次；
  - 仍不符 → 停止本批，在 `PARENT_SUMMARY.calibration.status="fail"` 列出每個不符項與 detail，**不跑**前沿案例。這本身就是有效交付，下一輪 brief 會處理。
- hvac 檔缺失或 sha 不符時：
  - CTRL_POS 與 CTRL_NEG 記為 blocked；
  - canary 改在 CTRL_SYN_T0/T1 上做；CANARY_FONT 記 not_run（合成頁只有一個字型）；CANARY_GROWTH 只做主站點（CTRL_SYN_T1，rotate=270，鄰字由 `tail_text` 提供），hvac 站點記 blocked；
  - `calibration.status="synthetic_only"`，可以繼續前沿案例，但每一案的 `calibration_ref` 都要標 `synthetic_only`。
- 正向增長控制：`CTRL_POS_T1.growth_zone.applicable` 不是 true，或其 `before_*` 任一不為 0（`before_drawings_intersecting_bbox` 除外）→ R0 不符。
- 合成控制：`CTRL_SYN_T0` 九個 phase 任一不 pass 或 `applicable` 不是 false → R0 不符；`CTRL_SYN_T1` 的 `probe.max_tier_1` 不是 `rejected`／`growth_region_not_blank`（detail 不以 `glyphs:` 開頭）、`probe.max_tier_0` 不是 `rejected`／`advance_mismatch`、`probe.commit.attempted` 不是 false、`mutation` 不是 null、或 `growth_zone.applicable=true` → R0 不符（`check_calibration` 逐項回報）。

## 3. 前沿類別（依序；class_id 沿用 F 編號）

### 3.0 共通規則

**reproducible 的門檻：**
- 同一 class 至少 2 個 save_reopen_pass 正例，來自 2 個以上不同 lineage（§3.7），而且都已通過 Claude 端的重新量測（實驗路徑的 status 在 remeasure 前只是假設）；
- 有 Tier 1 意義的 class：至少 1 個 Tier 0、至少 1 個 Tier 1，而且 Tier 0 與 Tier 1 必須是**不同 show**（同一 show 只能有一個正例）；
- 至少 1 個負例手足案（kind=negative），寫明 expected_reason，且該 expected_reason 必須在 §6.1 的預註冊 JSON 區塊裡**先**寫好；
- 只有 1 個 lineage，或全部正例屬於同一 producer 家族 → 只能提議 `method_reproducible_single_family` 或 `needs_second_case`。**single_family 與第二 lineage 門檻只看 save_reopen_pass 正例（v5 (w2)）**：negative 與 census 列的 lineage 與家族不算；v4 驗證器的 per_class 計數把它們算進去了（0032 的 F30B／F2I 由你記成 `method_reproducible_single_family` 是正確的），rev ≥ 5 起驗證器改以正例計數、rev 4 報告不變。
- **synthetic 不算 lineage**（H4）：`provenance=synthetic` 的紀錄只能是 kind ∈ {control, canary}（class_id ∈ {CTRL_SYN_T0, CTRL_SYN_T1, CANARY_GROWTH, CANARY_KSIGN}；§2.3 的 hvac 缺失 fallback 下其他 CANARY_* 也可以，`calibration_ref=synthetic_only`），不計入任何類別的 lineage 或 producer 家族，Claude 端的 `emit_rows` 也不會從它產生 manifest 列（CI 的合成孿生在 `frontier_twins.py`）；用白名單 builder 做出來的檔每次建檔 sha 都不同（隨機 trailer `/ID`，§2.1），同一組 `kwargs` 也不例外；不同 sha 不是不同來源，同一個 builder 的任何輸出都只是那一個 builder，跨批次以 `join_key`（`ctrl-syn/p0/show0`）對應，kind=positive／negative／census 配 synthetic 一律退件（§5.1）。
- **public 的定義是 repo 追蹤的 sha 表**：`provenance=public` 只承認 `test_scripts/fixtures/public_corpus_sha256.json`（tracked；sample-files-main、veraPDF-corpus-staging、Test-PDF-Files-master 的相對路徑 → sha256）裡的檔案。你在 §3 之外自己找到的公開檔照樣可以記錄（provenance 仍寫 `public`、relative_path + sha 照填），但 Claude 端的 rederive 會把 sha 不在表內的來源標成 `quarantined: provenance_unverified`：該案仍會被重新量測，卻不算第二個 lineage，所屬類別最多只能提議 `needs_second_case`，直到 owner 把該檔加進 sha 表。test_files/ 整個被 gitignore，所以「放進 test_files/ 再宣告 public」不會讓一份被改過的檔變成公開語料。
- **local_unrecorded 的定義也是 repo 追蹤的 sha 表**：`provenance=local_unrecorded` 只承認 `test_scripts/fixtures/true_text_corpus/manifest.json` 的 `corpora` 裡 `provenance="local_unrecorded"` 的四個檔（§3.2 的 test-colored-background 00640a01…、test-horizontal-texts e1c4920a…、test-hierarchy-bookmarks f93ba509…，§3.5 的 test-complexed-layout faefb744…；I0a 已登錄，四個 sha 都是在 owner 機器上對原檔重新計算的，不是抄自任何批次）。這四個檔的列 `source.relative_path` 要填 `test_files/…` 路徑（`brief_revision >= 4` 驗證器 `relative_path_required`，見 §5.1）；registry 靠 sha 解析，路徑只是讓列自帶檔案身分。若你的 checkout 還沒有這份 manifest，預期 `quarantined: provenance_unverified`，仍會被重新量測。sha 不在表內的 `local_unrecorded` 列與 public 列同樣處理：rederive 標成 `quarantined: provenance_unverified`，仍重新量測，但不算 lineage、所屬類別最多 `needs_second_case`，而且 `emit_rows` 不會從任何被隔離的案產生 manifest 列。`provenance=proprietary` 列只能是已登錄的 sha（acceptance `CORPORA` 的 hvac、ecc，以及 owner 決定後登錄的 office-report-23p）；不在表內 → `quarantined: before_pdf_mismatch`（無法解析，不量測）。所以把一份改過的檔放進 test_files/ 再宣告 public、local_unrecorded 或 proprietary，都不會變成第二個 lineage。**hvac（9da93de9…fca0a2）與 ecc（0f75dd10…b1853）的 provenance 一律是 `proprietary`（v3 (c)）**：它們以 sha 登錄在 `test_scripts/test_text_commit_real_corpus_acceptance.py` 的 `CORPORA = (HVAC, ECC)`（`HVAC.sha256`、`ECC.sha256`），`relative_path` 寫 null。寫成 `local_unrecorded` 不是「比較保守」：那個 sha 不在 local_unrecorded 的四檔表內，rederive 會整案 `quarantined: provenance_unverified`，兩次 pilot 的三個控制組全部因此被隔離、校準沒有定案。**驗證器不抓這個錯**：validate 對 provenance 只做 schema 詞彙、null 規則與 `synthetic_only_with_hvac_present`（唯一認得 `HVAC_SHA256` 的檢查；ecc 的 sha 根本不在驗證器裡），hvac／ecc 列寫成 `local_unrecorded` 會通過 validate 與 `--self-check`，直到 Claude 端 rederive 才整案 `quarantined: provenance_unverified`、不計校準。所以自我檢查「全綠」不代表 provenance 對；寫 `proprietary` 是你自己要對照 §2.1 表做到的事。

**replacement 選字規則：**
- 只用「同一 font xref 在本文件已經畫過」的字元（provenance = `chars_already_drawn_by_font`）；
- 等寬版用目標本身字元的排列（例如反轉；回文要跳過），provenance = `permutation_of_target`；
- 變寬版在尾端加一個已經畫過的字元；
- 簡單字型：不得含 `'`（0x27）與 `` ` ``（0x60）——產品對 encoding 不是 WinAnsi/MacRoman 的字型會以 `encoding_failed` 拒絕這兩個 slot（`fonts.py:149-150,319-322`）；若你故意要測這條，它是負例，expected_reason=`encoding_failed`；
- `unmappable`（v3 新 enum 值，(f)）：replacement 含至少一個該 font xref **畫不出來**的字（Type0 沒有 CID 對應、簡單字型 `encoding_failed` 的「字型缺 glyph」那一支）。**只准** kind ∈ {negative, control, census} 且 `mutation=null` 的列用——CTRL_NEG 依構造就是它（「路」不在 hvac C2_1 的子集裡）；census 列從不 mutate，常停在 `type0_unicode_unmapped`，同樣適用。**unmapped 家族**（驗證器 `UNMAPPABLE_REASON_EXEMPT_DETAILS` 的同一份定義）：`type0_unicode_unmapped`、`encoding_failed`、`type0_glyph_missing`、`type0_cid_out_of_map_range`、`type0_gid_zero`、`type0_gid_beyond_glyph_count`（後三個是產品 glyph gate 對每個被觸及的 CID 的解析失敗，每一個都表示該 glyph 畫不出來）；產品的 glyph gate 先查原文 CID、再查 replacement（`plan.py:2056`），兩側回同一個 detail 字面值，驗證器分不出是哪一側，所以 glyph gate 四個 reason（含 `type0_glyph_missing` 的缺 outline 分支）在原文側失敗時也一律要求 `unmappable`（fail closed），**但以下 detail 不算**（它們只說「無法證明」或講的是原文那一側，不是 replacement）：`type0_unicode_unmapped` 的 "a source code has no ToUnicode mapping" 與 "no CID maps to a character of the bound source text"、`encoding_failed` 的 "reverse encoder does not reproduce the source string bytes"、`type0_glyph_missing` 的 "embedded program's glyph tables are unreadable; no glyph can be proven present"；家族 reason 配上任何其他 detail 都算（fail closed）。規則：(1) kind=positive／canary 或 mutation 非 null 的列寫 `unmappable` 整案退件；(2) `mutation=null` 且任一 probe（max_tier_1 或 max_tier_0）的 reason／detail 落在家族內，`replacement_provenance` 不是 `unmappable` 就退件——**不論 kind**：positive 列選的是畫得出的字，家族 reason 推翻了這個選擇，所以它寫什麼都退件，這是 finding，不是改標籤；(3) 寫了 `unmappable` 卻沒有任何 probe reason 落在家族內，也退件（沒有證據支撐「畫不出來」）。它不是第三種選字方式，是「這個 replacement 不可能被畫出來」的誠實標記。
- 一律不得使用客戶、機構、案號等可識別字串。

**找 show 的方法：**
- 逐一走 `replay_page_streams([(x, doc.xref_stream(x)) for x in page.get_contents()]).shows`，`show_seq` 是該 tuple 的索引；
- 不得用 `get_text("words")` 找 show（那是 span/word，不是 show）。

**所有 case 都必須先出現在 §6.1 的預註冊 JSON 區塊裡**（class_id、slug、page_index、show_seq、variant、method_id、expected_reason）。計畫寫好後才找到的 show，本輪只能記成 census（kind=census，不做 mutation），下一輪再註冊。

### 3.1 第 1 名：F30 簡單字型的整段 show（產品已准入，但從沒有真實語料證明）
- **定義：** 目標 = 一個 Tj，或只有一個 string item 且**前面沒有 kern** 的 TJ，解碼後的全文。字型 Subtype 為 Type1 或 TrueType，沒有 /Differences，replacement 只用 0x20–0x7E 且不含 0x27/0x60。
- **目前產品行為：** 通常 PREPARED。負例碼（capability ladder 順序，`fonts.py:647-656`；再加 TJ 形狀）：`font_widths_incomplete`、`font_face_unavailable`、`font_unsupported_encoding`（Subtype 不是 Type1/TrueType，或 /Encoding 是具名的非標準編碼、MacExpert、Symbol 等）、`font_custom_differences`、`encoding_failed`（非 ASCII、quote slot、字型缺 glyph）、`tj_leading_kern_unproven`（單一 item 前有 kern）。

**F30B 子類：嵌入、沒有 /Encoding（built-in encoding 或 symbolic cmap）**
- 公開起點：
  - `test_files/sample-files-main/026-latex-multicolumn/multicolumn.pdf`，sha256 bdb495e95b3e1afae95013099dc59b0cea047f1fa70f677ee9cb33f10faa1c6c。p0 show3（CMBX12）與 p0 show49（CMR10），反轉替換在 HEAD a1d9a22 已實測 PREPARED Tier 0。
  - `test_files/sample-files-main/001-trivial/minimal-document.pdf`，sha256 f723638db6e763cf4ccadad38a3d38a02d9ecab95dab1f0bbf00e801991b5f92。p0 show7（CMR10）實測 PREPARED Tier 0。
  - `test_files/sample-files-main/009-pdflatex-geotopo/GeoTopo.pdf`，sha256 a0b9242aef9b5a2c4850160cc9aaf64f5c7b8be705d6872ae28aebf5ab512540。
- 以上都是 pdflatex 家族，所以 single_producer_family=true。請在 Type1|pfa|-、Type1|cff|-、TrueType|ttf|- 的非 LaTeX 檔中找第二個家族，例如 `test_files/Test-PDF-Files-master/not_encrypted.pdf`、veraPDF「6.3.8 Unicode character maps」資料夾。
- 負例手足：
  - `test_files/sample-files-main/013-reportlab-overlay/reportlab-overlay.pdf`，sha256 fdbdd49a118053577240850826a7eff6ac4ce7288527bf4c483714f0113860ed。字型 AAAAAA+Roboto-Regular，p0 show0–2 實測 `encoding_failed`。
- 解碼路徑證據（只記錄，不當正例）：
  - `002-trivial-libre-office-writer.pdf`（fc67ce4f76ffb44e818ebe4f673dbeb6002ad93a59f3856ff14fb1d3625f10a5）；
  - `016-libre-office-link/libre-office-link.pdf`（bc38b458acd125c09fb7603cf0cca5d8737eea9fe353c2aef2c42b3db9cf9076）。
  這兩檔的 show bytes 不是可列印 ASCII。
- **H-F30b 待證偽假設（false-safe）：** 產品把「沒有 /Encoding」的位元組當成 ASCII 反向編碼，但字型實際的 built-in encoding 或 (3,0)/(1,0) cmap 可能把同一個 code 畫成別的字形。
  - 判定**只能**看 §5.2 glyph_identity 的獨立腿（`glyph_name_agl` 或 `cmap_31_reverse`）；ToUnicode 不是獨立證據（MuPDF 的 texttrace unicode 與 get_text 都由 ToUnicode 決定，已實測：ToUnicode 說 A 的 glyph 畫 Z，兩者都回報 A）；
  - 若證實：status 照表計算，並在 PARENT_SUMMARY.product_findings 置頂，kind=`false_safe_suspect`。

**F30W 子類：嵌入、/Encoding 為 WinAnsi、MacRoman 或 Standard，沒有 /Differences，且不在 BDC/BMC 內**
- 公開檔中尚未找到不在 marked content 內的正例（UNVERIFIED）。請在 veraPDF 的 TrueType|ttf|WinAnsiEncoding（Isartor 6.3.x）與 TrueType|ttf|MacRomanEncoding（Isartor 6.5.x）檔中搜尋。這些檔多半是同一 producer 家族。
- hvac-dwg 有 5 個嵌入的 TrueType WinAnsi 字型，但整段 show 全部在 marked content 內，所以歸 F1。

**F30N 子類：未嵌入的 base-14（WinAnsi）**
- `test_files/sample-files-main/008-reportlab-inline-image/inline-image.pdf`，sha256 db5c34fea270f38b152d8476e6f3bba855460958e957f69a0542002538cac1c2。p0 show0（Helvetica）實測 PREPARED Tier 0。
- 未嵌入字型沒有字型程式，獨立腿改走 `standard_14_table`（§4 M0）：以 ISO 32000-1 Annex D 的 Standard/WinAnsi/MacRoman 表查 code → glyph name，再經 AGL。只有 basefont（去掉 subset 前綴）是 Standard 14 之一且 symbolic flag 為 false 才適用；否則 independent_leg=none → insufficient_evidence。
- `test_files/sample-files-main/024-annotations/annotated_pdf.pdf`，sha256 c327f921abfba23a5c42d5c429ba99ded1cf5511521003aba6d2aff9c940d9cc。這一頁的 /Annots 陣列裡是 3 個**內嵌（inline）**的 annotation dict（不是 indirect ref；`annot_xrefs()` 回傳三個 xref 0），在 HEAD a1d9a22 產品 `prepare` 會**拋出例外** AttributeError；T16-4X S10（本 brief 送出前必須已 commit，§1 的 `tracked_diff_empty` 才會是 true）把它改成拒絕：預期 `probe.max_tier_1.result="rejected"` 與 `probe.max_tier_0.result="rejected"`，reason 恰好是 `annotations_not_indirect`，detail 字面值 "3 of 3 listed /Annots entries are inline dictionaries (no xref)"（ASCII，§5.4），頁面 content streams 位元組不變，status 依 §5.3 規則 3 = probe_rejected（kind=negative，expected_reason=`annotations_not_indirect` 先寫進 §6.1）。indirect ref 陣列與 indirect /Annots 陣列照常 PREPARED。若你實際拿到的仍是 exception，代表 HEAD 沒有 S10：記 status=blocked、`probe.max_tier_1.result="exception"`，列入 product_findings，不要繞過。
- `test_files/1.pdf` 是測試產生的合成檔，不算獨立來源。

### 3.2 第 2 名：F1 結構化 marked content（產品下一個預定 slice 就是這一類）
- **定義：** 目標 show 外層有 BDC/BMC，但不是預設可見的純 /OC layer。依 `model.text_commit.marked_content.classify_wrapper` 的 slug 分子類：
  - `struct_content`：props **含 MCID、且沒有 ActualText/Alt**（其他 key 例如 Lang、E 今天被忽略；`marked_content.py:247-254`）。「只有 MCID」是 S2 計畫中的 inert-set 規則，不是現況；
  - `artifact`（tag 為 /Artifact，不看 props；`marked_content.py:324-325`）；
  - `bmc_bare`。
- **每案必記：**
  - wrapper 的 props：`props_kind`（replay `McWrapper.props_kind`：none／name／dict／unparsed）、`props_name`（name operand 時的 /Properties 資源名，例如 hvac 的 `MC0`；其餘 null）與 `props_keys` = `McWrapper.props_dict_keys`（**只有 inline dict 的頂層 key**；name operand 時為 `[]`，`replay.py:196-207`）。**不得**解析 /Properties 資源或 OCG 字典再把它的 key（Type、Name、Usage、Intent…）填進 `props_keys`——hvac p4 的 215 個 show 全在 `/OC /MC0`～`/MC2 BDC` 裡（Basis (9)），那樣填會讓每個 hvac 控制組與 canary 被 §5.4 第二層退件；本輪 schema 沒有 OCG 解析欄位（`additionalProperties=false`），驗證器在本機原檔上重算這三個欄位；
  - 經 `/StructParents` → `/StructTreeRoot /ParentTree`（number tree）→ 該頁的 `/StructParents` 整數 → wrapper 的 `MCID` 找到的 StructElem：`structelem_keys` **只記** {ActualText, Alt, E, Lang} 四個 key 裡該 StructElem 實際有的子集合（固定順序 ActualText、Alt、E、Lang；四個都沒有、wrapper 沒有 MCID、或 tree 沒有這一頁／這個 MCID 的項目 → `[]`；該頁沒有 `/StructParents` → `null`）。**不得**把 StructElem 的完整 key 集合（Table 323 的 S、P、K、Pg、ID、A、C、R、T…）填進去——那會在 §5.4 第二層被當成字串退件，而且驗證器在本機原檔上用同一條路徑重算這個欄位，不符就整案退件（§5.1，H2）；
  - 帶 ActualText 的 Artifact 要另外記錄成負例（classify 會先回 artifact）。
- **每個子類對應的現行拒絕碼（expected_reason 必須照這張表填，否則 §5.3 規則 3 判 insufficient_evidence）：**

| 子類 | expected_reason | detail 含 |
|---|---|---|
| `struct_content`、`artifact`、`bmc_bare`、`actual_text`、`alt_text`、`bdc_other`、`props_unresolved`、`props_unparsed` | `mc_wrapper_not_pure_layer` | `wrapper class: <slug>` |
| `oc_layer_hidden_default`、`oc_ocmd` | `mc_layer_not_default_visible` | `wrapper class: <slug>` |
| 未關閉的 wrapper、EMC underflow、wrapper 數與 mc_depth 不符 | `mc_malformed_pairing` | — |
| splice 範圍不在每個 wrapper span 內 | `mc_splice_crosses_wrapper_boundary` | — |

- **負例子類（每種至少 1 個）：** `actual_text`、`alt_text`、StructElem 帶 ActualText 或 Alt、Artifact 帶 ActualText、`props_unresolved`、`props_unparsed`、`bdc_other`、`oc_layer_hidden_default`（expected_reason=`mc_layer_not_default_visible`）。
- **起點：**
  - 公開：`test_files/veraPDF-corpus-staging/Isartor test files/doc/Isartor test suite manual.pdf`，sha256 f93735e19e367dc28af32899384577828693ec48926dc51a3a17abb2f8ea6053。p0 show2/3/4/6/8、p1 show20、p2 show40 實測 `mc_wrapper_not_pure_layer`；字型為 Verdana TrueType/Type1 WinAnsi 嵌入。
  - 公開（artifact 子類）：veraPDF「6.8.3 Artifacts」資料夾。
  - 來源不明（provenance=local_unrecorded，字串一律遮蔽；三個檔由 I0a 登錄在 manifest `corpora`，sha 與 §3.0 的表一致；`relative_path` 照填，登錄之前的 checkout 預期 `quarantined: provenance_unverified`，仍會被重新量測）：
    - `test_files/test-colored-background.pdf`，00640a01cecf0bfdf58bf72d6cbd20957ef98dcfc87b32f7f8b9e4a42eb36dba，p0 show0 實測同上；
    - `test_files/test-horizontal-texts.pdf`，e1c4920a310de4c894b70b037b6f935668405f41858800419c541c9e0028e3c4；
    - `test_files/test-hierarchy-bookmarks.pdf`，f93ba509283b805c629a48d2adc0b3a3a21412b8437fde1de28a5ae773fa5a78（Type0 hex Tj）。
  - 專有檔（只寫 slug + sha256）：
    - hvac（9da93de9…fca0a2），p1 show16，ArialMT TrueType WinAnsi，實測 `mc_wrapper_not_pure_layer`；
    - office-report-23p（880a637fe94734411fda89043e7abbe060b938b7a6dd09c04292bca19f8b320f）——**v5 起已登錄**（2026-10-26，owner 決定 7：`test_scripts/fixtures/true_text_corpus/manifest.json` 的 `corpora` 含這個 sha，`provenance="proprietary"`、slug 與 `lineage_id` 都是 `office-report-23p`；本機檔案已改名為 `test_files/office-report-23p.pdf`，你的 runner 以這個名字找它），所以可以做 positive／negative；registry 其餘來源是 `test_scripts/fixtures/public_corpus_sha256.json` 與 acceptance `CORPORA` 的 hvac／ecc。專有檔的列 `source.relative_path` 仍必須是 null，Claude 端只由 registry（manifest `corpora`、acceptance `CORPORA`）以 sha 解析來源，不在表內的專有來源一律 `quarantined: before_pdf_mismatch`（§3.0）。
- **額外交付（S2 的 inert-set 證據）：** 對每個 wrapper 類別，統計各 props key 的出現次數（MCID、Lang、E、ActualText、Alt、Type、Subtype、BBox、Attached……）。
- **E_F1 的 wrapper bytes 不變**是 structure phase 的硬條件（§5.2 的定義：BDC/BMC 與對應 EMC 的 token bytes 相同，offset 只因 `end_new − end_old` 平移）。

### 3.3 第 3 名：F2 多 item 的 kerned TJ
- **v4（V12）目標是整個 show 的「切片」：** F2I／F2R／F2G／F3 的 `corpus_case.original`、`target.item_range`、定位（`expected_origin_visual`、`target_bbox_*`）與 M1 probe 的 `target_text` 都是**切片**，整個 show 另記為第二個視角（`probe.whole_show_max_tier_1`）；定義見 §4 M0／M1 與 §5.1「目標粒度」，鄰字配對見 §5.2 neighbours。
- **現行拒絕碼（重要，與舊 brief 不同）：** 產品先做整段 show 的 binding（`inspect.py:1504-1508` 要求 `decoded_bytes == target_bytes`），再做 TJ 形狀 gate（`plan.py:1941` 先於 `plan.py:1998`）。所以：
  - 目標 = **一個 item** 或 **一段 item run**（短於整個陣列）→ `no_source_match`；
  - 目標 = 整個陣列串接後的全文 → `tj_multi_item_array`；
  - `tj_kern_in_tier1_range` **不是** F2 多 item 的碼：它只在單一 string item 的 TJ 帶尾端 kern、且 advance 不相等（變寬或縮短都算；`plan.py:2486-2497` 的 fence 沒有方向條件，Tier 1 由 `advance_mismatch` 任一方向進入）時才會到達（須先過 `_classify_common`）。這個形狀另記為 **F2K**。
- **K 的記錄方式（所有 F2 子類、E_KERN、M2 Tier 1 共用；§5.1 `advance` 物件——每個 mutation 必填，沒寫 number token 時 K_* 欄位為 null）：** `Tfs` 一律是 **Tf operand**（replay 的 `show.font_size`，`kern_for_displacement` 用的同一個數；hvac p4 s161 是 97.023、s26 是 132.01），不是乘 Tm 之後的有效字高；`Th` = `show.hscale/100`（s26 是 0.799805）。`K_written` = 實際寫進 stream 的數；`K_sum` = run **內部** kern 的總和（6 位小數；沒有內部 kern 時 0.0）；`K_disp_engine` = `kern_for_displacement(show, adv_old − adv_new)`；`K_disp_hand` = `1000·(adv_new − adv_old)/Tfs`。structure 檢查 `|K_written − (K_sum + K_disp_engine)| ≤ 1e-6` 與 `|K_disp_engine − K_disp_hand| ≤ 1e-6`。產品 Tier 1 與 E_KERN 的 `K_sum` 必為 0.0。
- **墨跡位移 `displacement_ink`（v3，R7-1 (i)；所有 mutation 必填）：** `splice_kind ∈ {tj_item, tj_run}` 時，增長證明的尺寸**不是** Δ = `adv_new − adv_old`，而是 `displacement_ink = Δ + K_sum·Tfs/1000`（text space、乘 Th 之前；`K_sum` = 這次 splice **新增或改變**的 kern 總和 = `internal_kerns_dropped` 的總和，TJ number 的單位是 1/1000 text-space em，所以 Σk·Tfs/1000 才是它們原本移走的 advance）。原因：F2R／F2G 把 run 內部的 kern 收進尾端的一個 K，新字串裡的字形不再被內部 kern 往回拉，after 的墨跡在增長側比 Δ 多出 Σk·Tfs/1000（正的 tightening kern → 多出來；負的 → 少掉）；只用 Δ 建 verify bbox，誠實的 F2G 列會被 §5.1「after 不得超過 verify + 0.5 pt」**誤退**，而且被證明空白的區域短了那一截（只靠產品 2 pt halo 蓋住）。`tj_item`（kern 全部不動）、`string_token`、`whole_operator`、`string_fragment`、`fragment_split` 與所有 product_commit 列的 `K_sum = 0.0`，所以 `displacement_ink == Δ`。`growth_pt`、`verify_bbox_visual`、`growth_zone.applicable`（experiment／canary 路徑）、raster 區域族全部改以 `displacement_ink` 計（§4 M4、§5.1 `advance.displacement_ink` 欄位、§5.2 growth_zone）；`K_written`、`K_disp_engine`、`K_disp_hand` 的定義與 1e-6 檢查**不變**（它們管後續文字的位置，不管目標墨跡）。
- **F2I：** 目標恰好等於陣列裡**一個** string item（kern 全部不動）。現行碼 `no_source_match`（整段才會是 `tj_multi_item_array`，另記一案 kind=negative 作對照）。splice_kind=`tj_item`，等寬，`advance` 物件必填（adv_old = adv_new，`K_written` 等 K_* 欄位為 null）。
- **F2R：** 目標等於連續 item run 的串接。現行碼 `no_source_match`。方法依 X5：
  - 寫成 `(new) K_sum`，其中 K_sum = run 內部 kern 的總和（6 位小數；K_sum == 0 時省略 number token）；`K_disp_engine` = 0.0（等寬）；
  - 邊界 kern 位元組不變，也不得合併進 K；run 在陣列末端時 K 仍要寫；
  - 必須記錄 `internal_kerns_dropped`。
  這些 pair kern 消失算不算不跳（X5）：**owner 已於 2026-10-28 裁定成立**（§0.2 第 8 點，算不跳），你照舊只量化並記錄。I4／I5 產品 slice 尚未落地，所以 F2R／F2G 本輪**仍是 measurement-only**——F2 本輪仍以 F2I（S4a）與 F2K 為主交付；F2R／F2G 照舊做實驗並完整記錄 `internal_kerns_dropped`、`displacement_ink`、in-show 偏差數字與 6x 裁切（owner 要靠這些數字裁定 X5），case `status` 照量測事實記（`splice_pass`／`save_reopen_pass` 是驗證器可重算的事實，不是准入判定），但 README 與 PARENT_SUMMARY `product_findings` 不得把 F2R／F2G 寫成「不跳已成立」或「可准入」，一律在 README `## Pilot limits` 註明「X5 待 owner 裁定」。**「X5 待 owner 裁定」只改 README／`product_findings` 的措辭，不是不登錄、不執行 F2R／F2G 的理由：`20261024_1803_r2` 因此 0 個 F2R／F2G 列，是退件形狀；兩者都必須預註冊（§6.1）、執行並完整記錄。** F2K（v5 (y)，owner 保留的範圍裁定，要求不變）：`20261026_0032_r2` 的有界掃描（已登錄來源各最多 60 頁；2922 個語料 PDF 各前 5 頁）沒有找到可達 `tj_kern_in_tier1_range` 的形狀，crazyones p0 s16／s24（SFRM0900 `/Differences`）兩列被上游的 `font_custom_differences`（F31／I8 的閘）擋下，不是 F2K 閘的 negative；F2K 保持已授權、開放，E_F2K 保留，I8 落地後重查這兩個 show，不得把 F2K 寫成「已完成 census」。**v5 補充（2026-10-26，owner 裁定）：full 批次不得「0 個 F2K 列且不掃描」。`20261026_0948_r2` 0 列、無新掃描，是退件形狀。下一批 full 必須在本機、於 `candidates/` 的副本上重做有界掃描，範圍至少同 0032（已登錄來源各最多 60 頁；語料 PDF 各前 5 頁），把掃描範圍、掃過的 show 數與到達 `tj_kern_in_tier1_range` 的數量寫進 README `## Pilot limits`；找到可達形狀就登錄 F2K 列（positive 或 negative 依 §6.1 預註冊）；找不到時，crazyones p0 s16／s24 照 0032 登錄為 F2K negative（觀察到的上游碼 `font_custom_differences` 照記，F31 census 列可同時保留），使 F2K 的 per_class 不為空且掃描有紀錄。**
- **F2G：** kerned TJ 裡的變寬替換：`(new) K`，其中 K = K_sum + `kern_for_displacement(show, adv_old_run − adv_new)`；邊界 kern 是另一個獨立 token。現行碼 `no_source_match`。splice_kind=`tj_run`。
- **F2K：** 單一 item TJ 帶尾端 kern，**advance 不相等的替換（變寬或縮短都算）**。現行碼 `tj_kern_in_tier1_range`（max_tier=1；`plan.py:2486-2497` 的 fence 沒有方向條件）；max_tier=0 時是 `advance_mismatch`。縮短版的 K 為負、`growth_zone.applicable=false`。方法：只替換 string item 這個 token 為 `(new) K`（splice_kind=`tj_run`；`K_sum`=0.0），尾端 border kern 的位元組不動，結果形狀 `[(new) K <border>] TJ`。
- **起點：**
  - `test_files/sample-files-main/004-pdflatex-4-pages/pdflatex-4-pages.pdf`，f17a09190ad8a04964d78115d8ba7fc7a298557274fa14932ba58612342b7dec（CMR10，前 3 頁 135 個 show 全是 multi-item；p0 show0 整段實測 `tj_multi_item_array`，item「Hel」實測 `no_source_match`）；
  - multicolumn.pdf（CMR10，144 個 show）；
  - `test_files/sample-files-main/021-pdfa/crazyones-pdfa.pdf`，f05f2738a1fa8c1d2e1147881fe1a62516a7f8caaf784067790731f56df626c4（SFTI1440 與 SFTI1200 是 WinAnsi、沒有 Differences；SFRM0900 有 Differences，屬於 F31 負例）；
  - Isartor manual：binding 先於 TJ gate 先於 MC gate，記錄 peel chain；
  - office-report-23p（專有；v5 起已登錄在 manifest `corpora`，見 §3.2，可做 positive／negative；`relative_path` 寫 null）。

### 3.4 第 4 名：F3 單一 string item 內的子字串
- **v4（V12）：** `byte_range_in_item` 是 item `i0` 解碼後位元組的區間，TJ 裡的 F3 另寫 `item_range = [i0, i0+1]`（索引，不是 stream 位移）；`corpus_case.original` 是這個切片的解碼文字，M1 probe 的 `target_text` 也是切片。負例「子字串在同一 item 裡出現兩次」就是用切片 probe（`no_source_match`）表達，不是用「整個 show 當目標、替換字串只換片段」的混合編輯。
- **定義：** 目標是某個 string item 解碼後的嚴格子字串。可以是 Tj literal/hex、單一 item 的 TJ，或多 item TJ 中的單一 item。
- **方法：**
  - `byte_range_in_item` = [b0, b1)，是**解碼後** item 位元組（literal 去跳脫、hex 解碼）上的區間；Type0 只能切在 2-byte 邊界；
  - 等寬（splice_kind=`string_fragment`）：只改 item 內的這個區間；**changes[] 仍以整個 string token 為單位記錄**（start = token 起點，old/new operand 為整個 token），讓驗證器能重新 lex。綁定只綁被替換的切片（§5.2 structure）：新 token 解碼後 `[0:b0]` 與舊 token 解碼後 `[0:b0]` 逐位元組相同、`[b0+len_new:]` 與舊的 `[b1:]` 相同、中段 `[b0:b0+len_new]` 等於 `glyph_identity[]` 的 `code_bytes_hex` 串接；配對用的字數差 = `len_new − (b1 − b0)`（code unit）；
  - advance 不相等——變寬或縮短都算（splice_kind=`fragment_split`，method_id `E_F3S`，kind=positive 時 variant 為 `grow`——negative／census 仍依 kind 寫 `neg`／`cen`，§5.1；縮短時 K 為負、`growth_zone.applicable=false`，與 F2K 同）——**兩種形式，依 `target.operator` 決定**：
    - `Tj`（或 `'`／`"` 不在本輪）：整個 operator 換成 `[(prefix)(new) K (suffix)] TJ`（changes[] 範圍 = 整個 `(old) Tj` operator）；
    - `TJ`（目標 item 在既有陣列裡——單一 item 帶 border kern，或多 item 陣列中的一個 item）：**只換那一個 string item token**，寫成就地、不加括號的 `(prefix)(new) K (suffix)`（changes[] 範圍 = 該 string token；巢狀陣列不合法）；陣列的 `[`、`]`、其他 item、每個 border kern 位元組不動（`border_kerns_byte_identical=true`），新 number 至多一個，所以帶尾端 border kern 的單一 item TJ 仍只多一個 number。
    兩種形式都是：prefix string 解碼後 = 舊 item 解碼後 `[0:b0]`（b0 = 0 時省略 prefix）、中段 string = `glyph_identity[]` 串接、suffix string = 舊的 `[b1:]`（b1 = len 時省略 suffix）；number 至多一個，只能在中段與 suffix 之間；prefix／suffix 至少一個非空（否則不是 F3，是 E_KERN）。
- **起點：** Isartor manual（整行 literal Tj）、multicolumn、minimal-document（CMR10 單一 item）、inline-image。
- **目前碼：** `no_source_match`（UI 端是 `target_reconstruction_unverified`）。必須填 `no_source_match_subclass`。
- **負例：** 子字串在同一 item 裡出現兩次；子字串緊鄰 TJ kern；literal 跳脫字元跨越切點；Tw≠0 且切點旁有空白。
- **遮蔽限制：** F3 的新 operand 含舊 item 的 prefix／suffix，那是文件位元組。非公開檔（provenance ∉ {public, synthetic}）只准 `font_kind=type0` 的 F3 列（payload 是 CID，§5.4 只對本機原檔綁定、不當文字掃）；簡單字型的 F3 列只能做公開檔或 synthetic（latin-1 payload 會進第二層掃描，prefix／suffix 的字必然不在白名單）。

### 3.5 第 5 名：F17 連續 show 之間沒有重新定位（先量測）
- **定義：** 第二個 show 的 `origin_reliable=False`，目前碼 `untracked_advance`（`inspect.py:1604-1607`）。
- **起點：**
  - `test_files/test-complexed-layout.pdf`，faefb744200aad617504802b72fd20c7525bab203f849f22a38af07f127bedf3（local_unrecorded；`relative_path` 照填；由 I0a 登錄在 manifest `corpora`，§3.0）；
  - `test_files/sample-files-main/015-arabic/habibi.pdf`，1017c4559eb7d0ccf7d151a3f051c8c1da27a7c1dc8050b2b687e3d3228e1b6f（同檔的 RTL 是 F29，要分開記錄）。
- **方法：** 用 /W 或 /Widths 加 Tc/Tw 推算前一個 show 的 advance，預測下一個 show 的 origin，與 texttrace 比對（≤ 0.02 pt，這裡是「定位」容差）。至少 2 個 lineage 預測成立，才可以做等寬 splice。

### 3.6 只做特性描述（census，kind=census；不做 splice，不得宣稱成功）
- **F31（/Differences）：** crazyones 的 SFRM0900；Isartor manual 的 BMFGlossary（encoding 為空但帶 Differences）。記錄每個 Differences 名稱的 AGL 解析結果，以及嵌入字型程式內是否有該 glyph。
- **F5（Type3）：**
  - google-doc-document.pdf（69f6b7f493b1bc55d518942976cbeadc4ec0a36f6d8a6dc24feffc516d35b2c9）；
  - test-complexed-layout.pdf；
  - `isartor-6-3-4-t01-fail-g.pdf`（2200684c391ffb8be11724db93fa45211670e6d29201b88ecae079ad8f3cd7ad）。
  記錄 FontMatrix、/Widths、/Differences、/ToUnicode、CharProcs 是否齊全。
- **F4（Form XObject 內的文字）：**
  - `test_files/Awareness.pdf`（2cdee708c3a8ff01b3e7e7ebad500323a879f3a9d82ac369fcf6b87094564347；頁面 content 實測沒有 show）；
  - veraPDF「6.2.5 Form XObjects」資料夾。
  記錄：該 XObject 在全文件被引用幾次（所有頁、巢狀 form、/AP、pattern）、/BBox、/Matrix，以及變寬後是否超出 /BBox。
- **F6（Tier 1 增長區旁有線、框、圖）：** hvac 或 ecc（0f75dd10ed77214c5cf159d40f909cd402231761886cb0ed3821368ac0ab1853）的副本。只量測增長 strip 與最近墨跡的距離（用 §5.2 growth_zone 的同一個 strip 與座標轉換），不得嘗試繞過，也不得自創門檻。
- **公開 Type0 probe 健康檢查：** `test_files/sample-files-main/022-pdfkit/pdfkit.pdf`（8820ba44cd62264fd561e921aacc214cee7ba76723f525d591cdb2104a87f0dd），只做 1 案 M1 probe。

**本輪不碰（遇到時只記 probe 碼與一行觀察，不花 attempts）：**
- F8–F16、F19–F29；
- F18（`3 Tr` 不可見文字）：owner 決定 1 已定——**本輪拒絕、不授權**，只記 probe 碼與數量，不花 attempts；
- F9：不得擴充 subset。

### 3.7 獨立性（lineage）
「不同來源 PDF」以 lineage 判定，不以 sha256 判定。以下各組各算**一個** lineage：
- GeoTopo 與 GeoTopo-komprimiert；
- test-large-file 與 test-large-file.damaged；
- 20260129 / _1 / _2；
- habibi 的各變體；
- Isartor 同一測試號的 t01-fail-a/b/c；
- 同一文件的不同頁。

每案都要記錄 /Producer、/Creator（專有檔要遮蔽）、`lineage_id` 與判定理由、`producer_family`。

### 3.8 `mode: census`（v10 (aw)；v11 (ay)–(be) 重寫）：全語料普查（唯讀，不是案例批次）
目的：0000、1809、2156 三個 full 批次形狀完全相同（§15 (ax)），同一份 §3 再跑不會有新資訊；下一輪需要新的候選。v10 的第一次普查（`20261030_0007_census`）給了文件層的計數，但沒有「每個 show 的形狀 × 它的字型能力」的 join，挑案例還要再掃一次；v11 讓每個檔直接帶 `census_show_shapes.census()` 的結果。本模式**只量測，不判斷**。
- **適用範圍**：只在 owner 貼上 `mode: census` 時。Poppler gate 不適用（不 render）；§1 的 denylist 前置條件與 §7 適用（不得修改 `test_files/`、不得 taskkill、不跑 pytest、輸出不得含絕對路徑）。**git 只准 §1 列出的唯讀指令**（`rev-parse`、`status --porcelain`、`diff`、`ls-files`、`check-ignore`）；`code_revision` 的欄位與算法照 §1 的 `code_revision` 一節，由本批次的 `run_census.py` 在開任何 PDF 之前於行程內計算，只放進 `CENSUS.json` 的 `code_revision`，**不另寫 `code_revision.json`**（本模式的批次目錄只含下面四種檔案）；其中 `runner_sha256` 是本批次 `run_census.py` 位元組的 sha256。（v10 把這條轉述成「不得 git」，與 §1 矛盾，以 §1 為準。）
- **census 模式唯一放寬（直接開原檔）**：`run_census.py` 直接 `fitz.open(<`test_files/` 底下的原檔>)`；§1 helper 一節的「只開 `candidates/` 裡的副本」與 v5 (aa) 在本模式不適用（普查要看約 2,942 個檔，而「把 PDF 複製出 `test_files/`」被禁止）。不得呼叫任何寫入 API（`save`／`saveIncr`／`ez_save`／`embfile_*`／`set_metadata`／`xref_set_key`／`update_stream`、annotation 寫入）；每個檔用完 `doc.close()`。
- **denylist 缺檔（停止形狀）**：`test_files/.redaction_denylist.txt` 不存在 → blocked bundle：`README.md` 第一行 `blocked: test_files/.redaction_denylist.txt missing`、第二行 `mode: census`；`DONE.json` 為 `{"stamp": "<YYYYMMDD_HHMM>_census", "record_count": 0, "census_sha256": null, "readme_sha256": "<hex64>", "runner_sha256": "<hex64>"}`；**不寫 CENSUS.json**，不編造 hash。然後停止。
- **批次目錄** `_evidence_pilot/<YYYYMMDD_HHMM>_census/`，只含：`run_census.py`（本戳記自己的副本；重跑方式 `.venv\Scripts\python.exe -B _evidence_pilot\<stamp>\run_census.py`；helper 只能放 `helpers/` 並在 README 列出）、`CENSUS.json`、`README.md`、`DONE.json`。`run_census.py` 只能 import 標準庫、`fitz`、repo 的 `model.text_commit.*`、本批次自己的 `helpers/`，以及 `scripts.census_show_shapes`（唯讀 import `census`；**不得複製或改寫它的邏輯**，不得 monkeypatch）。README 第一行寫 `mode: census`，只陳述數字與各 outcome 的檔數，不得有成功或推薦的宣稱。**沒有** `cases/`、PARENT_SUMMARY.json、VALIDATION.self.json；Claude 端的讀取器在收到這一輪之後才寫。
- **掃描範圍**：`test_files/` 底下遞迴所有副檔名（不分大小寫）為 `.pdf` 的檔案；不跟隨 symlink 與 junction。排序鍵是以 `test_files/` 開頭、以 `/` 分隔的 POSIX 相對路徑的 UTF-8 位元組（不用 `\`，否則次序與 sha 會因分隔符而不同）。每個檔：
  - 讀 bytes 失敗（算不出 sha256）→ `read_failed`；`fitz.open` 失敗，或 `doc.is_pdf` 為 false → `open_failed`；`doc.needs_pass` 為 true → `encrypted`（**不呼叫 `authenticate`**、不掃頁）；其餘進入量測。
  - **抽頁（v11 (ay)，取代 v10 的「前 50 頁」）**：每檔最多 50 頁。頁數 `n` ≤ 50 → 全掃；`n` > 50 → **等距抽 50 頁**，索引是 `sorted({round(i * (n - 1) / 49) for i in range(50)})`（Python 的 `round`，含首頁與末頁；與 `census_show_shapes.census(path, 50, …)` 內部同一個式子）。`pages_scanned` 是實際抽到的頁數。上限不拿掉：語料裡有一個 10,000 頁的檔（第一次普查實測）；改的是取樣位置，前 50 頁只看得到封面與目錄。
  - **同一組頁、同一個預算**：`census()` 與下面的手寫計數用同一組抽到的頁。replay 一律用預設預算（`model.text_commit.replay.DEFAULT_MAX_REPLAY_BYTES`，4 MiB），**不得傳 `None`**：呼叫是 `census(path, 50, True, max_decoded_bytes=DEFAULT_MAX_REPLAY_BYTES)`。超過預算的頁沒有 show，那不是「這頁沒有字」，`census()` 會把它算進 `pages_replay_refused`（replay 回報 malformed 的頁算進 `pages_replay_malformed`）。
  - **單檔失敗不中止**：每個檔 `try/except Exception`。任何量測 raise（含 PyMuPDF 內部例外）→ 這個檔 `page_error`：所有量測欄位為 null，只記 `exception_class`（類別名），不記訊息文字。
- **每個檔一筆**，欄位固定（缺值寫 null；不得省略欄位、不得自創欄位）：
  - 身分：`sha256`（完整 64 hex 重算）、`size_bytes`、`outcome`（enum：`scanned`／`open_failed`／`encrypted`／`page_error`／`read_failed`）、`exception_class`（Python 類別名，或 null）、`provenance`、`relative_path`、`path_matches_registry`、`slug`。
    - `provenance`：`public` = sha 在 `test_scripts/fixtures/public_corpus_sha256.json` 的 `files[].sha256`；`local_unrecorded`／`proprietary` = sha 在 `test_scripts/fixtures/true_text_corpus/manifest.json` 的 `corpora[].sha256` 且該項 `provenance` 為該值（兩張表的 sha 不重疊）；其他一律 `unregistered`，**不推測**。`read_failed` 的 `sha256` 為 null，`provenance` 為 `unregistered`。
    - `relative_path`：只有 `public` 與 `local_unrecorded` 寫，且寫**登錄表裡的** `relative_path`（POSIX、`test_files/` 開頭），不是磁碟上找到它的路徑；其餘一律 null。`path_matches_registry`：磁碟上的相對路徑等於表內路徑 → true，否則 false；`relative_path` 為 null 時 null。
    - `slug`：`public` 依 §5.1 的規則；`local_unrecorded`／`proprietary` 取 manifest `corpora[].slug`；`unregistered` 為 null。
  - 文件：`page_count`、`pages_scanned`、`encrypted`（`doc.is_encrypted`；空 user password 仍可掃，所以 `scanned` 的列也可以是 true）、`producer_sha256`（`{"producer": hex64|null, "creator": hex64|null}`：`doc.metadata` 的 `producer`／`creator` 的 UTF-8 各取 sha256；缺或空字串寫 null）、`producer_text`（`{"producer": str|null, "creator": str|null}`；**只有 `provenance == public` 可寫**，其餘一律 null——§5.4 對 provenance ∉ {public, synthetic} 的遮蔽也適用於 `local_unrecorded`）。**`producer_family` 刪除**：v10 寫「§3.7 的家族判定」，但 §3.7 沒有機械的家族規則，那是判斷，不是量測；家族由 Claude 端自己判定。`outcome` 為 `open_failed`／`encrypted`／`read_failed` 時，`page_count`、`pages_scanned`、`producer_*` 與所有量測欄位都是 null（`encrypted` 欄位：`encrypted` 列寫 true，另兩種 null）；`page_error` 的列保留文件欄位，量測欄位為 null。
  - 量測（只有 `outcome == scanned` 才有，其餘 null）：
    - **`census`**：`census_show_shapes.census()` 的回傳物件，**逐字照放**（鍵名不改、不增不減）：`pages_total`、`pages_sampled`、`pages_replay_refused`、`pages_replay_malformed`、`shows_total`、`shape`、`render_modes`、`kern_numbers_by_class`、`kerned_shows_by_item_class`、`text_state_flags`、`fonts_by_capability`、`font_dict_shapes`。它是 show 形狀 × 字型能力的 join；`fonts_by_capability` 的 key 帶 `reject=<tier0 reject reason|ok>`，是挑候選的主要欄位。
    - **手寫計數**（v10 已有的欄位，名稱與定義不變，只改為在同一組抽到的頁上算；show 的定義是 §3.0 的 `replay_page_streams(...).shows`，不得用 `get_text`）：`shows_total`、`shows_tj`、`shows_tj_array`、`shows_quote`（`'` 與 `"`）、`tj_array_items_ge2`（TJ 的字串 item 數 ≥ 2 的 show 數）、`tj_array_with_kern`（含非零 kern 的 TJ show 數）、`shows_in_bdc_mcid`（在至少一層「內嵌屬性字典帶 `/MCID`」的 BDC 內的 show 數；經 `/Properties` 資源名間接引用的 MCID 不解析）、`shows_in_bdc_other`（在 BDC／BMC 內、但沒有上述包裝的 show 數，與前者互斥）、`shows_tr3`（`3 Tr` 之下）、`shows_in_form_xobject`（`page.get_xobjects()` 列出的每個 Form XObject stream 各 replay 一次、依 xref 去重，每檔一次；**不計入** `shows_total`）、`pages_with_sh`（§5.2 的頁級 token-aware `sh` 規則，`verify._page_has_shading_operator`；replay 被拒絕的頁不做這個掃描，已由 `pages_replay_refused` 揭露）、`pages_rotated`（`/Rotate` 繼承值 mod 360 ≠ 0 的頁數）、`pages_user_unit_ne_1`；字型 `fonts_simple_embedded`、`fonts_simple_nonembedded`、`fonts_type0_identity_h`、`fonts_type0_other`、`fonts_type3`、`fonts_with_differences`、`fonts_with_tounicode`（取 `page.get_fonts(full=True)`、抽到的頁，以 font xref 去重；simple = Type1／MMType1／TrueType；embedded = 副檔名欄不是 `n/a`；Type0 identity_h = `/Encoding /Identity-H`）。
- **不得**：宣稱 F 類別、推薦候選、打分數、寫「適合」「可行」之類的判斷（census 不得宣稱成功，§3.6）；mutation、`prepare`／`commit`；把 PDF 複製出 `test_files/`；把任何 PDF 的文字內容、檔名、路徑，或 Producer／Creator 字串（`public` 的 `producer_text` 除外）寫進輸出。Claude 端自己用這些計數挑下一輪的候選並登錄。
- **外洩閘門（v11 (bc)；census 不經驗證器，所以閘門在 `run_census.py` 自己身上）**：
  - `limits` 是**字串清單**（不得放 dict 或 list）：每個字元在 0x20–0x7E，只有數字與欄位名，不含檔名、路徑、Producer／Creator 或 PDF 文字；指稱單一檔只能用 `sha256` 的前 8 碼。README 同一條規則。單檔的結果（outcome、例外類別、被拒絕的頁）一律只放在該檔那一筆，不放進 `limits`。
  - `run_census.py` 與 `helpers/` 不得含 `test_files/` 底下任何檔名（只准兩張登錄表的路徑與目錄名 `test_files`）。
  - **寫任何輸出檔之前**，`run_census.py` 讀 `test_files/.redaction_denylist.txt`，以 §5.4 第一層規則（拉丁條目逐字、大小寫不分、整字比對；CJK 條目子字串比對）掃**記憶體中**的 CENSUS.json 與 README.md 的每一個字串，含 JSON 物件的 key。命中在 `producer_text` 或 `relative_path` → 該欄位改寫 null；命中在其他任何地方 → blocked bundle（README 第一行 `blocked: denylist hit outside producer_text/relative_path`，`DONE.json` 的 `record_count: 0`、`census_sha256: null`，不寫 CENSUS.json）。命中數記為 `limits` 的一行 `denylist_hits: <n>`（0 也寫；不寫命中內容）。
- **`CENSUS.json`**：`{"schema": "true-text-census/2", "stamp": "<YYYYMMDD_HHMM>_census", "brief_revision": 11, "code_revision": {同 §1 的 code_revision，runner_sha256 是 run_census.py}, "tool_versions": {"python": "<版本>", "pymupdf": "<版本>"}, "sampling": {"page_cap": 50, "rule": "even_spacing_first_last"}, "replay_budget_bytes": <DEFAULT_MAX_REPLAY_BYTES>, "inventory": {"files_found": n, "by_outcome": {"scanned": n, "open_failed": n, "encrypted": n, "page_error": n, "read_failed": n}, "by_provenance": {"public": n, "local_unrecorded": n, "proprietary": n, "unregistered": n}}, "files": [...], "limits": ["…"]}`；`limits` 逐條寫沒做到的事（例如超過 50 頁、被抽頁的檔數）與 `invariant_violations: <n>`。**不變量**（Grok 自查並把違反數寫進 `limits`；Claude 端也會重驗）：`len(files) == files_found == Σ by_outcome == Σ by_provenance`；每個 `scanned` 的列：`census.shows_total == shows_total`、`census.pages_sampled == pages_scanned`、`shows_total == shows_tj + shows_tj_array + shows_quote`。
- **單次執行、寫入順序**：全部 records 必須來自同一次 `run_census.py` 執行；中途失敗（程序死掉、沒有 `DONE.json`）→ 整個戳記作廢，由 owner 重貼、用新戳記，**不得續跑、不得拼接**。寫入順序：`CENSUS.json`（以 `"wb"` 寫入 UTF-8 位元組，`json.dumps(..., ensure_ascii=True)`，換行 LF，不得用文字模式——Windows 會寫成 CRLF）→ `README.md` → `DONE.json` 最後。
- **`DONE.json`**（最後一個寫入的檔案）：`{"stamp": "<YYYYMMDD_HHMM>_census", "record_count": <int>, "census_sha256": "<hex64>", "readme_sha256": "<hex64>", "runner_sha256": "<hex64>"}`。三個 sha 都是對**關檔後重新從磁碟讀回的位元組**算的完整 64 hex；`record_count == files_found`；寫完之後不得再改任何檔（`readme_sha256` 與 `runner_sha256` 讓 Claude 端偵測事後被改）。
- 檔案編碼同 §1 的「檔案編碼與型別」：每個 .json／.md／.py 嚴格 UTF-8、無 BOM，不含絕對路徑、使用者名稱或主機名；直譯器只寫成 `.venv\Scripts\python.exe -B`。

## 4. 每案方法梯（依序，不得跳步；每個實驗只改一個變因）

**M0 身分與定位**
- 對來源檔重算完整 64 位 hex 的 sha256，執行前後各算一次，必須相同。
- 複製到 `candidates/<case_id>/before.pdf` 與 `work_copy.pdf`；再對 before.pdf 算一次 sha256 寫進 `source.before_pdf_sha256`，必須等於 `source.sha256`（驗證器重算檔案 sha；Claude 端量測從不開你的 before.pdf，§0）。
- 找到 show_seq，依字型類型解碼：
  - Type0：`DocumentFontRegistry(doc).capability(page, res).cid.decode_show_bytes(show.decoded_bytes)`；
  - 簡單字型：`show.decoded_bytes.decode("latin-1")`（與 binder 同腿），replacement 另外要求 0x20–0x7E（與 encoder 同腿）。另外用**獨立管道**再解一次，優先順序固定：
    1. `glyph_name_agl`：字型程式自己的編碼得到 glyph 名稱，再經 `fontTools.agl.toUnicode`。編碼來源：Type1 cleartext 的 `dup n /name put`，或 `/Encoding StandardEncoding def`（內建編碼 = ISO 32000-1 Annex D 的 Standard 表）、CFF encoding/charset，或 TrueType 依 ISO 32000-1 §9.6.6.4 的 (3,1)/(3,0)/(1,0) cmap 加 `post` 表名稱。**Type1（FontFile）的 gid 配方固定為：** code → 內建編碼（cleartext `dup n /name put`，否則 StandardEncoding 表）→ glyph 名稱 → AGL unicode → `gid = fitz.Font(fontbuffer=<FontFile 位元組>).has_glyph(unicode)`（FreeType 的 glyph index，MuPDF 畫圖用的同一個載入器；回 0 = 沒有）；要求 `gid != 0` 且 `== gid_after`。不得用 `fontTools.t1Lib.T1Font` 直接開嵌入的 FontFile（CM 字型的 stream 沒有 cleartomark 尾段，`T1Error: can't find end of eexec part`；若要用 fontTools 必須先補 512 個 0 與 `cleartomark`，而且算出的 gid 仍須等於 fitz 的）；
    2. `cmap_31_reverse`（只限 TrueType 且 `post` 沒有名稱，例如 post format 3 的 Office 子集）：code 依 §9.6.6.4 走 cmap 得到 gid，再在同一支字型的 (3,1) cmap 反查該 gid 對應的 Unicode。這是字型程式**自己**的身分宣告，與 `post` 名稱、與 PDF 的 ToUnicode 都無關；
    3. `standard_14_table`（只限未嵌入、basefont 為 Standard 14、symbolic flag false）：Annex D 表查 code → glyph name → AGL；
    4. 否則 `none`（**ToUnicode 不算簡單字型的獨立腿**）。
    結果寫入 `target.source_decode`。兩者不一致時，記錄為 F30b 發現。**v4（V12）：`source_decode` 解的一律是整個 show 的 `decoded_bytes`（`latin1`、`independent` 與兩個 sha256 都是整個 show），不是目標切片；切片寫在 `corpus_case.original`（§5.1「目標粒度」）。整個 show 解碼文字的 sha256 另寫進 `corpus_case.show_text_sha256`，所以非公開檔也能核對 show 的身分。****非公開檔（provenance ∉ {public, synthetic}）：`latin1` 與 `independent` 欄位寫 null，只填 `latin1_sha256`／`independent_sha256`（UTF-8 的 sha256）；`agrees` 照實填。**

**M1 產品路徑 probe（必做，一律先做）**
1. Handle A = 量測副本 `fitz.open("pdf", doc.tobytes(encryption=fitz.PDF_ENCRYPT_KEEP))`，在上面取 texttrace：
   - 依 decode 後的**整個 show** 文字比對（v4：先定位整個 show 的 run，目標切片在 run 內再取，見下面「切片」一條）；
   - 取 origin 最接近 `fitz.Point(show.origin_user) * frame.base` 的匹配（`frame` 見下一條；texttrace 的座標在 `frame.base` 空間——**不是** `page.transformation_matrix`：它在 /Rotate ≠ 0 時丟掉 CropBox 原點與 /UserUnit，/UserUnit 2 的頁差 400 pt 以上，Basis 的 round-6 probe；H3），誤差必須 < 0.02；
   - `frame = transforms.page_visual_frame_or_none(pageA)`（None → 該案 blocked，`page_geometry_unsupported`）；`expected_origin = Point(chars[0][2]) * frame.quarter_turn`（`origin_recipe="texttrace_chars0_x_quarter_turn/v1"`）；
   - `target_bbox_raw` = 各字 bbox 的聯集；`target_bbox_visual` = `target_bbox_raw × frame.quarter_turn`。
   - **切片（v4，V12）：** 目標是整個 show 時，上面三條照 run 的 `chars[0]` 與整個 run 的 bbox 聯集（與 v3 相同）。目標是切片（`target.item_range` 或 `target.byte_range_in_item` 非 null）時，先照上面用 `show.origin_user * frame.base`（< 0.02 pt）定位**整個 show 的 run**，再取目標在 run 內的字形子區間 `[c0, c0+n)`：`n` = 目標位元組數 / code unit（Type0 為 2、簡單字型為 1），`c0` = 目標之前的字形數 = 「第 `i0` 個 string item 之前所有 string item 的位元組數 + `byte_range_in_item` 起點 `b0`（沒有就是 0）」/ code unit。`expected_origin` = 子區間 `chars[0]` 的 origin × `frame.quarter_turn`，`target_bbox_raw` = 子區間各字 bbox 的聯集。子區間的 texttrace unicode 必須等於 `corpus_case.original`，對不上就是定位錯了（記 blocked，原因寫進 `limits`）；**禁止**拿 `original` 自己去 texttrace 搜尋當作定位。
   - **untracked origin（v4，V13）：** `text_state.before.origin_reliable == false`（前面有 show 的 advance 沒被追蹤，`show.origin_user` 屬於更早的 show）時**不做 texttrace 定位**——拿這個 origin 去定位只會量到別的 show 的字形（2116 的 F17 列就是這樣）。`target.expected_origin_visual`、`target.target_bbox_visual`、`target.target_bbox_raw` 三個欄位**一起寫 null**（schema 在 `brief_revision >= 4` 允許，其他情況仍是必填的非 null），`limits[]` 加一條說明原因（例如 `Untracked origin (origin_reliable false): the three target geometry fields are null, the probe ran with expected_origin=None.`）。M1 的 probe 照做，但 `expected_origin=None`、`target_bbox=None`：這是第 6 條「禁止換 origin 重試」**唯一**的例外，因為它不是重試——這一列從頭到尾只有這一個 probe，沒有第二組 origin 可換。
   - **positional 定位（v4，V13）：** 只在「文字比對找不到目標、而且 `origin_reliable == true`、而且 texttrace 的 unicode 讀不出來」時使用——定位用的 glyph 是 U+FFFD 或 private-use（例如沒有 ToUnicode 的 Wingdings TrueType、Type3 字型）。取離 `fitz.Point(show.origin_user) * frame.base` 小於 0.02 pt 的**唯一**一個 glyph 當錨點（兩個以上 → 不可用），再取它起算的 `n` 個 glyph：`n` = `len(show.decoded_bytes)` / code unit（Type0 為 2、簡單字型為 1，Type0 不論 CID codec 解不解得出來）；這 `n` 個 glyph 必須在同一個 texttrace run 裡連續（同一個字型），錨點 glyph 的 unicode 必須是 U+FFFD 或 private-use。切片目標照上面「切片」取子區間。`expected_origin`／`target_bbox_*` 照常寫非 null 的值，`limits[]` 加一條以 `locate_method: positional` 開頭的說明；文字比對成功的列不寫 `locate_method`（rederive 報告的 `remeasured.locate_method` ∈ {`text`, `positional`}，沒有這個鍵就是 `text`）。錨點 glyph 讀得出來卻對不上文字 → 不是這個分支，記 blocked（原因寫進 `limits`）。
2. Handle B = 新開的 `fitz.open(work_copy)`，呼叫前不得在 B 上做 texttrace、get_text 或 get_cdrawings：
   `TieredCommitEngine(docB, max_tier=1).prepare(pageB, target_text=..., replacement_text=..., expected_origin=..., target_bbox=...)`
   v4（V12）：`target_text` = `corpus_case.original`（目標切片，不是整個 show）、`replacement_text` = `corpus_case.replacement`、`expected_origin`／`target_bbox` = 上面切片的值；`probe.max_tier_1`／`probe.max_tier_0` 記的就是這個切片 probe，`expected_reason` 也以它為準。切片目標（`item_range` 或 `byte_range_in_item` 非 null）另做**整個 show 的第二個視角**：`target_text` = 整個 show 的解碼文字、`replacement_text` = 目標之前的文字 + `replacement` + 目標之後的文字（一個前後文一致的整段編輯）、`expected_origin`／`target_bbox` = 整個 show run 的值（`chars[0]` 與整個 run 的 bbox 聯集）；另開一個新 handle、`max_tier=1`，結果寫進 `probe.whole_show_max_tier_1`（形狀同 `probe_result`；整個 show 為目標的列寫 null）。這個視角是 `tj_multi_item_array` 之類整段 gate 的證據，不是切片列的 `expected_reason`。**切片目標一定要寫這個視角**（驗證器 `whole_show_view_required`，缺鍵或 null 都退件）。
3. 在另一個新開的 handle C 上，用 `max_tier=0` 再做一次。
4. 兩個結果都記錄：
   - 被拒：reason 與 detail；
   - 例外：exception_type（S10 之後 inline /Annots 頁不再是例外而是 `annotations_not_indirect` 拒絕，§3.1）；
   - 成功：tier、stream_xref、replacement.start/end、binding.show.op_start/op_end、font_xref、source_advance、replacement_advance（**Tier 0 兩者是 0.0**——`PreparedEdit` 的預設值，`plan.py:165-166`，只有 `_build_tier1` 會填；照抄 0.0，不得用實測值補，§5.1 (b)）、kern_adjustment，以及 `verify_bbox_page` 與 `background_bbox_page` **原值照抄**（Tier 0 兩者為 null；Tier 1 是產品的 `_grown_verify_bbox` 與字型度量框，進 `target.verify_bbox_visual`／`growth_zone.background_bbox_visual`，驗證器以 1e-3 對公式重算——float32 往返差約 2e-5，§5.2）。
5. 必須驗證 `binding_matches_target`：binding 的 (stream_xref, op_start) 等於 `shows[show_seq]`，且 [replacement.start, replacement.end) ⊆ [op_start, op_end)。不符 → insufficient_evidence。
6. 禁止換 origin 重試（untracked origin 的列例外：見第 1 條「untracked origin」，那一列的 probe 本來就只有一個，用 `expected_origin=None`）。

**M2 產品 commit（只在 M1 PREPARED 時）**
- 在 handle B 上執行 `engine.commit(prepared)`，對 work_copy.pdf 做 `saveIncr`。
- 在新的量測副本上再取一次 texttrace，記 `target.after_bbox_raw`／`after_bbox_visual`（替換字形 bbox 聯集，§5.1）與 neighbours.json 的 `role=target` 紀錄；跑完 §5.2 的九個 phase，`mutation.path="product_commit"`。`advance.adv_old_text_space`／`adv_new_text_space` 一律用 M4 的產品函式實測（Type0 `advance_points`、簡單字型 `plan._advance`）：Tier 1 兩者必須等於 `prepared.source_advance`／`replacement_advance`，Tier 0 的 `prepared.*` 是 0.0、不是量測值（§5.1 (b)）。`changes[]` 的唯一一筆**照抄** `prepared.replacement`：`start`／`end_old` = `replacement.start`／`replacement.end`，`new_operand_bytes_hex` = `replacement.replacement_bytes`——Tier 0 是 string token `<CID…>` 的範圍（`show.string_start/string_end`，不含 operator，`plan.py:2304-2308`），Tier 1 是整個 operator（`op_start/op_end`，形狀 `[<CID…> K] TJ`）。

**M3 gate peel（純診斷；只在 M1 被拒時）**
- 在 `candidates/<case_id>/peel-<n>.pdf` 上，只移除 reason 指向的**一個**特徵，例如：拿掉 BDC/EMC、把 TJ 拆成單一 item、把 Tr 改成 0。
- 重跑 M1，記錄下一個拒絕碼，最多 3 層。
- peel 結果永遠不算成功，也不得出現在驗收 crop 裡。

**M4 物件層實驗（只在 M1 被拒時）**
- splice 一律用 `model.text_commit.pdf_lexer.splice_stream` 與 `model.text_commit.dto.StreamReplacement`。
- 切點必須在**原始 operand bytes** 上，以 `pdf_lexer.lex_content_stream` 重新 lex 求得，且 **對齊 token 邊界**；禁止用 decoded_bytes 推算 offset。
- **每案恰好一個 `changes[]` 範圍**（splice_kind ≠ canary 時）。第二個範圍——不論多小——整案退件。
- 新 operand bytes 的 token 文法依 splice_kind 固定（§5.2 structure）；多一個 operator 就整案退件。新 string token 解碼後的位元組必須等於 `glyph_identity[]` 各字 `code_bytes_hex` 依序串接（含 `is_space=true` 的空白碼），長度等於 replacement 的 code unit 數（簡單字型 1 byte/字，Type0 2 bytes/字）。**`string_fragment`／`fragment_split` 例外：只綁被替換的切片，prefix／suffix 必須與舊 operand 解碼後逐位元組相同（§3.4、§5.2）。**
- 每個 mutation 都要填 §5.1 `advance` 物件（adv_old／adv_new／Tfs／Th／advance_tolerance／`displacement_ink` 必填；`displacement_ink = (adv_new − adv_old) + K_sum·Tfs/1000`，`splice_kind ∉ {tj_item, tj_run}` 時等於 Δ，§3.3 R7-1；`Tfs` 是 Tf operand、`Th` = `show.hscale/100`；`advance_tolerance` 是產品對該 advance source 的容差，§5.2；沒有 number token 時 K_* 為 null），以及 `target.after_bbox_*`、`target.verify_bbox_visual`、`target.user_unit`（= `frame.user_unit`）、`target.trm_scale`（= `math.hypot(linear[0], linear[1])`，`linear = transforms.combined_linear(show.tm, show.ctm)`；**不是** `hypot(*linear)`，§5.2）與 neighbours.json 的 `role=target` 紀錄，以及 `growth_zone.background_bbox_visual`——一律用產品函式 `transforms.map_text_quad_to_visual(page, show.tm, show.ctm, (x_pre*Th, -0.35*Tfs, (x_pre + adv_old_text_space - K_inner/1000*Tfs)*Th, Tfs), frame=frame)` 算（沒有 kern 的整個 show 為目標時是產品 `_build_tier1` 的同一個 quad，`plan.py:2505-2516`；實驗路徑與產品路徑沒有任何輸入差異；`x_pre` = 切片之前所有 string item 的 advance（算法同 §5.1 的 adv_old），加上切片前每個 kern 數字 K 的 −K/1000·Tfs；F3 再加 item i0 裡 b0 之前位元組的 advance；整個 show 為目標時 `x_pre` = 第一個 string item 之前的 kern 總和的 −K/1000·Tfs（Tj 與無前置 kern 的 TJ 為 0）；`K_inner` = 切片內部、string item 之間的 kern 數字總和（切片之前的 kern 屬於 x_pre、切片之後的不算；單 item、F3、Tj 為 0；整個 show 為目標的 TJ 是所有 item 之間的 kern 總和）；沒有 kern 的整個 show（Tj）公式與產品 `_build_tier1` 相同，§5.2）；`growth_zone` 的適用性、方向、區域與 render 遮罩面積都由驗證器從這些欄位重算（§5.1、§5.2）。**`applicable=true` 時 `target.after_bbox_visual` 在主增長邊的延伸（`verify._growth_zone_rect(target_bbox_visual, after_bbox_visual)` 的主邊延伸量；None 視為 0）不得超過 `verify_bbox_visual` 的延伸（`_growth_zone_rect(target_bbox_visual, verify_bbox_visual)`）+ 0.5 pt**（產品 own-char 邊界容差，`verify.py:1467-1478`；H1）——after 的墨跡不得跑出被證明空白的區域；texttrace 的字形框是 advance 框（Basis (11)），誠實的列兩者只差浮點雜訊。
- K 的規則：
  - `K_disp_engine`：一律呼叫產品函式 `model.text_commit.patch.kern_for_displacement(show, displacement)`，其中 `displacement = adv_old − adv_new`（與 Tier 1 的 `source_advance - replacement_advance` 同號，`patch.py:385`）；等寬時 0.0；
  - adv 是 text space、乘 Th 之前的原始值：Σ(w/1000·Tfs) + Σ Tc（簡單字型的 byte 32 再加 Tw）；**adv 不含任何 TJ kern**。**一律用產品函式算**（`advance_function` 記函式名）：簡單字型 `model.text_commit.plan._advance(capability, text, show.font_size, show.char_spacing, show.word_spacing)`（→ `FontCapability.string_width`，`fonts.py:254`；`capability = DocumentFontRegistry(doc).capability(page, show.font_resource)`），Type0 `capability.cid.advance_points(cids, show.font_size, show.char_spacing)`（`cid_fonts.py:1029`；/W 第一個命中的紀錄，否則 /DW）；`advance_source` 照 `capability.advance_source` 填（`widths` → `Widths`、`face` → `face`、`cid` → 新舊 operand 的每個 CID 都命中 /W 紀錄時 `W`、否則 `DW`）。Claude 端的 rederive 用同一組函式在本機原檔上重算 adv_old／adv_new／advance_source，差超過 `advance_tolerance` → `quarantined: remeasure`（H1）；
  - `K_disp_hand = 1000·(adv_new − adv_old)/Tfs` 交叉驗證，\|K_disp_engine − K_disp_hand\| ≤ 1e-6；
  - `K_sum` = run 內部 kern 的總和（只有 E_F2R／E_F2G 非零；其餘 0.0）；同時 `displacement_ink = (adv_new − adv_old) + K_sum·Tfs/1000`（v3 必填；`growth_pt = max(0, displacement_ink)·Th·trm_scale·user_unit`，verify bbox 以它延伸，§3.3、§5.2）；
  - `K_written = K_sum + K_disp_engine`，\|差\| ≤ 1e-6；寫入格式與產品相同：6 位小數；
  - 舊批次的自寫公式作廢。
- 依類別的預定實驗：
  - `E_STR`：等寬字串 token（splice_kind=`string_token`）；
  - `E_KERN`：變寬，trailing K（splice_kind=`whole_operator`，形狀 `[(new) K] TJ`）；
  - `E_F1`：只在 wrapper 內 splice，wrapper bytes 不動（§5.2 定義）。另做一個惰性對照：在**另一份**副本拿掉該 BDC/EMC，2x 整頁算圖必須與原檔逐像素相同；
  - `E_F2I`（`tj_item`）、`E_F2R`／`E_F2G`／`E_F2K`（`tj_run`）：見 §3.3；
  - `E_F3`（`string_fragment`）、`E_F3S`（`fragment_split`）：見 §3.4；
  - `E_F17`：見 §3.5（splice_kind=`string_token`）。

**停止規則：**
- 同一案連續 3 次嘗試都沒有新證據 → 停止，status 照 §5.3 計算，並寫明 next_check；
- 每案最多 3 個假設，只有一個主要變因。

## 5. 證據契約

### 5.1 每案 `cases/<case_id>/case_record.json`；`cases.json` 為其陣列（兩者內容必須一致）
- `case_id` 依規則產生，不得自取：`r2-<class_id>-<source_sha256 前 8 碼>-p<page_index>-s<show_seq>-<variant><k>`
  - variant ∈ {`eq`, `grow`, `neg`, `ctrl`, `can`, `cen`}；k 從 1 起。詞彙封閉，不得自創（`20261024_2116_r2` 為 E_F3S 列自創 `split`，計畫列與 case_id 都不合法）。依 kind 決定：control → `ctrl`、canary → `can`、census → `cen`、negative → `neg`；kind=positive 看計畫的 replacement 相對目標的 advance（§5.1 `advance`）：相等（`advance_tolerance` 內，新 operand 沒有 number token）→ `eq`，不相等 → `grow`。**`grow` 的意思是「advance 改變」：變寬與縮短都寫 `grow`**（F2K 的縮短版、advance 不等的 F3 `fragment_split` 都是；縮短時 K 為負、`growth_zone.applicable=false`）。method 不決定 variant：同一個 show 的 E_F3（等寬）與 E_F3S（advance 改變）是 `eq` 與 `grow` 兩列。
  - 範例：`r2-F30B-bdb495e9-p0-s3-eq1`。
- `join_key` = `<slug>/p<page_index>/show<show_seq>`，與產品 UI 測試的 case id 格式相同。
- `slug`（`source.slug`、§6.1 計畫列的 `slug`、`join_key` 的前段，三者必須相同）依來源機械產生，不得自取：公開檔與 local_unrecorded 檔 = `relative_path` 的檔名主幹（去掉 `.pdf`）轉小寫，每一段連續的 `[a-z0-9]` 以外字元（含 `.`、`_`、空白與 `-` 本身）換成一個 `-`，再去掉頭尾的 `-`——與 Claude 端 rederive 的 `_slugify`（`scripts/evidence_rederive.py`）同一規則；`brief_revision >= 4` 的驗證器核對 `slug == _slugify(Path(relative_path).stem)`（`slug_not_derived`；公開檔與 local_unrecorded 檔 `relative_path` 非 null，`relative_path_required`）；例：`Isartor test suite manual.pdf` → `isartor-test-suite-manual`、`annotated_pdf.pdf` → `annotated-pdf`、`veraPDF test suite 6-8-3-3-t01-fail-a.pdf` → `verapdf-test-suite-6-8-3-3-t01-fail-a`（`20261024_2116_r2` 寫成 `vera-6-8-3-3-t01-fail-a`，那是更正，不是新規則）、`ua2-8.2.5.20-t02-pass-a.pdf` → `ua2-8-2-5-20-t02-pass-a`。專有檔 = acceptance `CORPORA` 的 `slug`（`hvac`、`ecc`）；synthetic = `ctrl-syn`（驗證器自 v10 起強制，`synthetic_slug`，§15 (au)）。結果必須符合 `^[a-z0-9][a-z0-9-]*$`；檔名主幹沒有任何 `[a-z0-9]` 字元的檔本輪不得登錄。`slug` 不是 `lineage_id`（`isartor-6-3-4-t01-fail-g.pdf` 的 slug 是 `isartor-6-3-4-t01-fail-g`，lineage 是 `isartor-6-3-4-t01-fail`）。`20261024_2116_r2` 把五個 veraPDF PDF/UA 檔名的 `.` 原樣抄進 slug（例如 `ua1-7.2-t30-pass-b`），計畫列與 case 都違反 pattern。
- schema 只驗型別與詞彙；通過門檻寫在 §5.2，status 由 §5.3 重算。schema 之外，驗證器對檔案本身另有五條不分 brief_revision 的退件：`json_unparseable`（含 UTF-8 BOM）、`json_duplicate_key`、`file_not_utf8`、`file_unreadable`、`integer_expected`（計數／索引寫成 bool 或 `12.0`），§1 檔名規則。**驗證器不信任 `phases.*.result`：每個 phase 都從同一份紀錄的數值欄位重算，不一致就整案退件。** 這是算術交叉檢查，不是量測；**量測由 Claude 端的 rederive 重做**（原檔由本機語料庫以 `source.sha256` 解析、`changes[]` 的位元組在紀錄裡；你交的 before.pdf 從不被開啟，§0），任何數字對不上 → `quarantined: remeasure`。所以「失敗的案例」一定能合法表達，「自報 pass」沒有用，「數字一致但不真」也沒有用。
- `neighbours.records_file`（`cases/<case_id>/neighbours.json`）的每筆紀錄只准有這些 key：`trace_index_before`(int|null)、`trace_index_after`(int|null)、`show_index`(int；無法歸屬到任何 replay show 的字形寫 −1)、`char_index_before`(int|null)、`char_index_after`(int|null)、`gid_before`(int|null)、`gid_after`(int|null)、`origin_before`(num2|null，raw texttrace 空間)、`origin_after`(num2|null)、`bbox_before`(num4|null)、`bbox_after`(num4|null)、`origin_delta_pt`(number|null)、`role`(`untouched`|`inshow_successor`|`target`)、`is_space`(bool，texttrace unicode 的 `isspace()`，對應產品 `_iter_nonspace_chars`)、`ink_checked`(bool)、`ink_changed_px_6x`(int|null)、`overlap`(bool)、`halo_shadowed`(bool)、`ink_after_px_6x`(int|null；只有 `role=target` 且 `is_space=false` 的紀錄非 null：after 6x crop 內、該字形 `bbox_after` 範圍裡與 crop 嚴格多數色不同的像素數，§5.2 neighbours)。**沒有 unicode、沒有 glyph name、沒有文字**。`role=target` 的紀錄**每個目標字形一筆**（before 與 after 依 char index 配對；變寬時多出的 after 字形 before 欄位為 null，縮短時相反）；驗證器用它重算 `neighbours` 物件的每個數字，並以 `role=target` 的 `bbox_after` 聯集重算 `target.after_bbox_raw`（1e-3，bbox 比較一律 float32-aware）。

- **目標粒度（v4，V12；`brief_revision >= 4` 的列必須照這一條，v3 沒有定義這些欄位的語意）：**
  - `corpus_case.original` = **目標**的解碼文字：`string_token`、`whole_operator`、product_commit = 整個 show；`tj_item` = 那一個 item；`tj_run` = run 內各 string item 的串接（kern 不算）；`string_fragment`、`fragment_split` = item `i0` 解碼位元組 `[b0, b1)` 的解碼。`original_sha256` = 該字串 UTF-8 的 sha256。非公開檔照 §5.4：`original` 寫 null、sha256 照填。
  - 新欄位 `corpus_case.show_text_sha256` = **整個 show** 的解碼文字（M0 的 `decode`）UTF-8 的 sha256，**每列必填**（整個 show 為目標的列，它等於 `original_sha256`）；必須等於 `target.source_decode.latin1_sha256`。
  - `target.item_range` = TJ 陣列裡 string item 的**索引**半開區間 `[i0, i1)`（只數 string item，不數 kern number；`0 ≤ i0 < i1 ≤ array_item_count`）。Tj、`'`、`"` 與整個陣列為目標 → null。F3 必須 `i1 == i0 + 1`，而且 TJ 裡的 F3 一定要寫 `item_range`；`byte_range_in_item` 是 item `i0` **解碼後**位元組的區間（Type0 只能切在 2-byte 邊界）。它們**不是** stream 位元組位移；stream 位移在 `mutation.changes[0].start`／`end_old`。
  - `changes[0]` 的範圍：`tj_item`、`tj_run` = item `[i0, i1)` 在 stream 裡的 lexed 範圍（第 `i0` 個 string item 的起點到第 `i1−1` 個的終點，中間的 kern 含在內，兩端的 border kern 不含）；`string_fragment` = item `i0` 的 string token 本身；`fragment_split` 在 TJ 裡也是該 token，在 Tj 時是整個 operator（§3.4）。
  - 切片目標的 `advance`：`string_fragment`／`fragment_split` 的 `adv_old_text_space` = 切片 `[b0, b1)` 位元組（item `i0` 解碼後）的 advance，`adv_new_text_space` = `glyph_identity[]` 依 `index` 排序的 `code_bytes_hex` 的 advance；item 裡切片前後的前綴／後綴**都不算**（它們沒有變，Δ 只屬於切片）。`tj_item`／`tj_run` 照舊是 item／run 的 string item 串接（kern 不算）。Claude 端的 rederive 用同一個切片重算（M4、§0）。
  - 切片目標的 `expected_origin_visual`、`target_bbox_raw`、`target_bbox_visual` 是切片子區間的值（§4 M1「切片」）。`no_source_match_subclass`：目標是單一 item 的一部分或整個 item → 陣列有多個 string item 時 `substring_of_multi_item_tj_item`、只有一個時 `substring_of_single_string_item`；目標橫跨 ≥ 2 個 item → `spans_tj_items`；整個 show 為目標 → 依原規則（通常 null）。Claude 端的 rederive 會從原檔重算這個欄位。
  - Claude 端的 rederive 從原檔的 `stream[op_start:op_end]` 解出 string item，用 `item_range`／`byte_range_in_item` 取出目標，再核對 `original`、`original_sha256`、`show_text_sha256`、`changes[0]` 的範圍與解碼內容、定位、probe；**不採信紀錄裡的目標文字**。
- **幾何欄位、`font_kind` 與 `target_unlocatable`（v4，V13）：**
  - `target.expected_origin_visual`、`target.target_bbox_visual`、`target.target_bbox_raw` 只在 `text_state.before.origin_reliable == false` 時可為 null，而且三個一起；其他列一律非 null（§4 M1「untracked origin」）。null 的列 `limits[]` 必須有說明。
  - `corpus_case.font_kind` 由 `target.font_subtype`（字型字典的 `/Subtype`）決定：`Type0` → `type0`，`Type3` → `type3`，`Type1`／`MMType1`／`TrueType` → `simple`。**與 CID codec（產品的 `cap.cid`）解不解得出來無關**：沒有 CID codec 的 Type0（`source_decode.leg == none`，產品 probe 回 `type0_tounicode_unparseable`）仍寫 `type0`。這種字型沒有可用的 `advance.advance_function`，所以只做 census（`kind=census`，不 splice）；要做 mutation 的列一律 `insufficient_evidence`，`observation` 寫 `advance_unprovable`。
  - `target_unlocatable` 是 Claude 端 rederive 的 quarantine 代碼，不是你要寫的欄位：rederive 自己定位不到目標（untracked origin、positional 的前提不成立、文字比對失敗）時，該列 quarantine，**不拿 rederive 自己的定位失敗跟你的 probe 比對**，也不會當成產品例外；這一列不會被 ingest，但不是你的 record 錯誤。

```json
{
 "$schema": "https://json-schema.org/draft/2020-12/schema",
 "$id": "true-text-case/2",
 "type": "object",
 "additionalProperties": false,
 "required": [
  "schema_version",
  "brief_revision",
  "case_id",
  "join_key",
  "class_id",
  "subclass",
  "kind",
  "status",
  "product_success",
  "accepted_for_code",
  "calibration_ref",
  "methods_plan_sha256",
  "pre_registered",
  "source",
  "corpus_case",
  "target",
  "probe",
  "text_state",
  "mutation",
  "growth_zone",
  "neighbours",
  "glyph_identity",
  "extraction",
  "render",
  "save_reopen",
  "phases",
  "observation",
  "hypotheses",
  "next_check",
  "attempts",
  "peel_chain",
  "code_revision",
  "tool_versions",
  "command",
  "timestamp",
  "artifacts",
  "limits",
  "redaction"
 ],
 "properties": {
  "schema_version": {
   "const": "true-text-case/2"
  },
  "brief_revision": {
   "enum": [
    2,
    3,
    4,
    5,
    6,
    7,
    8,
    9,
    10,
    11
   ]
  },
  "case_id": {
   "type": "string",
   "pattern": "^r2-[A-Z0-9_]+-[0-9a-f]{8}-p[0-9]+-s[0-9]+-(eq|grow|neg|ctrl|can|cen)[0-9]+$"
  },
  "join_key": {
   "type": "string",
   "pattern": "^[a-z0-9][a-z0-9-]*/p[0-9]+/show[0-9]+$"
  },
  "class_id": {
   "enum": [
    "CTRL_POS_T0",
    "CTRL_POS_T1",
    "CTRL_NEG",
    "CTRL_DET",
    "CTRL_SYN_T0",
    "CTRL_SYN_T1",
    "CANARY_KSIGN",
    "CANARY_TC",
    "CANARY_FONT",
    "CANARY_UNSAVED",
    "CANARY_WRONGGLYPH",
    "CANARY_INK",
    "CANARY_GROWTH",
    "F30B",
    "F30W",
    "F30N",
    "F1",
    "F2I",
    "F2R",
    "F2G",
    "F2K",
    "F3",
    "F17",
    "F31",
    "F5",
    "F4",
    "F6",
    "OUT"
   ]
  },
  "subclass": {
   "type": [
    "string",
    "null"
   ]
  },
  "kind": {
   "enum": [
    "positive",
    "negative",
    "control",
    "canary",
    "census"
   ]
  },
  "status": {
   "enum": [
    "probe_rejected",
    "splice_pass",
    "save_reopen_pass",
    "insufficient_evidence",
    "blocked",
    "out_of_scope_vector"
   ]
  },
  "product_success": {
   "const": false
  },
  "accepted_for_code": {
   "const": false
  },
  "calibration_ref": {
   "enum": [
    "pass",
    "synthetic_only",
    "not_applicable"
   ]
  },
  "methods_plan_sha256": {
   "$ref": "#/$defs/hex64"
  },
  "pre_registered": {
   "type": "boolean"
  },
  "source": {
   "type": "object",
   "additionalProperties": false,
   "required": [
    "slug",
    "relative_path",
    "provenance",
    "sha256",
    "sha256_after_run",
    "before_pdf_sha256",
    "lineage_id",
    "lineage_reason",
    "producer_family",
    "single_producer_family",
    "producer",
    "creator",
    "page_count",
    "page_rotation",
    "synthetic_builder"
   ],
   "properties": {
    "slug": {
     "type": "string",
     "pattern": "^[a-z0-9][a-z0-9-]*$"
    },
    "relative_path": {
     "type": [
      "string",
      "null"
     ],
     "pattern": "^test_files/[^:\\\\]+\\.pdf$"
    },
    "provenance": {
     "enum": [
      "public",
      "local_unrecorded",
      "proprietary",
      "synthetic"
     ]
    },
    "sha256": {
     "$ref": "#/$defs/hex64"
    },
    "sha256_after_run": {
     "$ref": "#/$defs/hex64"
    },
    "before_pdf_sha256": {
     "$ref": "#/$defs/hex64"
    },
    "lineage_id": {
     "type": "string"
    },
    "lineage_reason": {
     "type": "string"
    },
    "producer_family": {
     "type": "string"
    },
    "single_producer_family": {
     "type": "boolean"
    },
    "producer": {
     "type": [
      "string",
      "null"
     ]
    },
    "creator": {
     "type": [
      "string",
      "null"
     ]
    },
    "page_count": {
     "type": "integer",
     "minimum": 1
    },
    "page_rotation": {
     "enum": [
      0,
      90,
      180,
      270
     ]
    },
    "synthetic_builder": {
     "anyOf": [
      {
       "type": "null"
      },
      {
       "type": "object",
       "additionalProperties": false,
       "required": [
        "callable",
        "kwargs"
       ],
       "properties": {
        "callable": {
         "type": "string",
         "pattern": "^test_scripts\\.[a-z0-9_]+\\.[a-z_][a-z0-9_]*$"
        },
        "kwargs": {
         "type": "object"
        }
       }
      }
     ]
    }
   }
  },
  "corpus_case": {
   "type": "object",
   "additionalProperties": false,
   "required": [
    "page_index",
    "show_seq",
    "original",
    "original_sha256",
    "replacement",
    "replacement_sha256",
    "font_resource",
    "basefont",
    "font_kind",
    "expected_outcome",
    "expected_reason",
    "expected_tier",
    "expected_tj_compensation"
   ],
   "properties": {
    "page_index": {
     "type": "integer",
     "minimum": 0
    },
    "show_seq": {
     "type": "integer",
     "minimum": 0
    },
    "original": {
     "type": [
      "string",
      "null"
     ]
    },
    "original_sha256": {
     "$ref": "#/$defs/hex64"
    },
    "show_text_sha256": {
     "$ref": "#/$defs/hex64"
    },
    "replacement": {
     "type": "string",
     "minLength": 1,
     "pattern": "^[^\\r\\n]+$"
    },
    "replacement_sha256": {
     "$ref": "#/$defs/hex64"
    },
    "font_resource": {
     "type": "string"
    },
    "basefont": {
     "type": "string"
    },
    "font_kind": {
     "enum": [
      "type0",
      "simple",
      "type3"
     ]
    },
    "expected_outcome": {
     "enum": [
      "commit_tier0",
      "commit_tier1",
      "refuse"
     ]
    },
    "expected_reason": {
     "type": [
      "string",
      "null"
     ]
    },
    "expected_tier": {
     "enum": [
      0,
      1,
      null
     ]
    },
    "expected_tj_compensation": {
     "type": [
      "number",
      "null"
     ]
    }
   }
  },
  "target": {
   "type": "object",
   "additionalProperties": false,
   "required": [
    "stream_xref",
    "op_start",
    "op_end",
    "operator",
    "string_kind",
    "array_item_count",
    "item_range",
    "byte_range_in_item",
    "font_xref",
    "basefont_raw",
    "font_subtype",
    "font_embedding",
    "font_file3_subtype",
    "encoding",
    "has_differences",
    "tounicode",
    "symbolic_flag",
    "descendant_subtype",
    "origin_recipe",
    "expected_origin_visual",
    "target_bbox_visual",
    "target_bbox_raw",
    "after_bbox_visual",
    "after_bbox_raw",
    "verify_bbox_visual",
    "trm_scale",
    "user_unit",
    "no_source_match_subclass",
    "replacement_provenance",
    "source_decode"
   ],
   "properties": {
    "stream_xref": {
     "type": "integer"
    },
    "op_start": {
     "type": "integer"
    },
    "op_end": {
     "type": "integer"
    },
    "operator": {
     "enum": [
      "Tj",
      "TJ",
      "'",
      "\""
     ]
    },
    "string_kind": {
     "enum": [
      "literal",
      "hex",
      "array"
     ]
    },
    "array_item_count": {
     "type": "integer",
     "minimum": 0
    },
    "item_range": {
     "type": [
      "array",
      "null"
     ],
     "items": {
      "type": "integer"
     },
     "minItems": 2,
     "maxItems": 2
    },
    "byte_range_in_item": {
     "type": [
      "array",
      "null"
     ],
     "items": {
      "type": "integer"
     },
     "minItems": 2,
     "maxItems": 2
    },
    "font_xref": {
     "type": "integer"
    },
    "basefont_raw": {
     "type": "string"
    },
    "font_subtype": {
     "enum": [
      "Type0",
      "TrueType",
      "Type1",
      "MMType1",
      "Type3"
     ]
    },
    "font_embedding": {
     "enum": [
      "FontFile",
      "FontFile2",
      "FontFile3",
      "none"
     ]
    },
    "font_file3_subtype": {
     "type": [
      "string",
      "null"
     ]
    },
    "encoding": {
     "type": "string"
    },
    "has_differences": {
     "type": "boolean"
    },
    "tounicode": {
     "enum": [
      "present",
      "missing",
      "unparseable"
     ]
    },
    "symbolic_flag": {
     "type": [
      "boolean",
      "null"
     ]
    },
    "descendant_subtype": {
     "type": [
      "string",
      "null"
     ]
    },
    "origin_recipe": {
     "const": "texttrace_chars0_x_quarter_turn/v1"
    },
    "expected_origin_visual": {
     "anyOf": [
      {
       "type": "null"
      },
      {
       "$ref": "#/$defs/num2"
      }
     ]
    },
    "target_bbox_visual": {
     "anyOf": [
      {
       "type": "null"
      },
      {
       "$ref": "#/$defs/num4"
      }
     ]
    },
    "target_bbox_raw": {
     "anyOf": [
      {
       "type": "null"
      },
      {
       "$ref": "#/$defs/num4"
      }
     ]
    },
    "after_bbox_visual": {
     "anyOf": [
      {
       "type": "null"
      },
      {
       "$ref": "#/$defs/num4"
      }
     ]
    },
    "after_bbox_raw": {
     "anyOf": [
      {
       "type": "null"
      },
      {
       "$ref": "#/$defs/num4"
      }
     ]
    },
    "verify_bbox_visual": {
     "anyOf": [
      {
       "type": "null"
      },
      {
       "$ref": "#/$defs/num4"
      }
     ]
    },
    "trm_scale": {
     "type": "number"
    },
    "user_unit": {
     "type": "number"
    },
    "no_source_match_subclass": {
     "enum": [
      "substring_of_single_string_item",
      "substring_of_multi_item_tj_item",
      "spans_tj_items",
      "spans_multiple_show_ops",
      "in_form_xobject",
      "not_decodable_by_registry",
      "text_not_in_any_show",
      null
     ]
    },
    "replacement_provenance": {
     "enum": [
      "chars_already_drawn_by_font",
      "permutation_of_target",
      "unmappable"
     ]
    },
    "source_decode": {
     "type": "object",
     "additionalProperties": false,
     "required": [
      "latin1",
      "latin1_sha256",
      "independent",
      "independent_sha256",
      "leg",
      "agrees"
     ],
     "properties": {
      "latin1": {
       "type": [
        "string",
        "null"
       ]
      },
      "latin1_sha256": {
       "anyOf": [
        {
         "type": "null"
        },
        {
         "$ref": "#/$defs/hex64"
        }
       ]
      },
      "independent": {
       "type": [
        "string",
        "null"
       ]
      },
      "independent_sha256": {
       "anyOf": [
        {
         "type": "null"
        },
        {
         "$ref": "#/$defs/hex64"
        }
       ]
      },
      "leg": {
       "enum": [
        "glyph_name_agl",
        "cmap_31_reverse",
        "standard_14_table",
        "cid_tounicode",
        "none"
       ]
      },
      "agrees": {
       "type": [
        "boolean",
        "null"
       ]
      }
     }
    }
   }
  },
  "probe": {
   "type": "object",
   "additionalProperties": false,
   "required": [
    "engine",
    "handle",
    "max_tier_1",
    "max_tier_0",
    "binding_matches_target",
    "commit"
   ],
   "properties": {
    "engine": {
     "const": "TieredCommitEngine"
    },
    "handle": {
     "const": "fresh_no_texttrace"
    },
    "max_tier_1": {
     "$ref": "#/$defs/probe_result"
    },
    "max_tier_0": {
     "$ref": "#/$defs/probe_result"
    },
    "whole_show_max_tier_1": {
     "anyOf": [
      {
       "type": "null"
      },
      {
       "$ref": "#/$defs/probe_result"
      }
     ]
    },
    "binding_matches_target": {
     "type": [
      "boolean",
      "null"
     ]
    },
    "commit": {
     "type": "object",
     "additionalProperties": false,
     "required": [
      "attempted",
      "status",
      "tier",
      "font_actions"
     ],
     "properties": {
      "attempted": {
       "type": "boolean"
      },
      "status": {
       "type": [
        "string",
        "null"
       ]
      },
      "tier": {
       "enum": [
        0,
        1,
        null
       ]
      },
      "font_actions": {
       "type": "array",
       "items": {
        "type": "string"
       }
      }
     }
    }
   }
  },
  "text_state": {
   "type": "object",
   "additionalProperties": false,
   "required": [
    "before",
    "after",
    "target_equal",
    "nontarget_shows_equal",
    "show_count_before",
    "show_count_after",
    "operator_count_before",
    "operator_count_after"
   ],
   "properties": {
    "before": {
     "$ref": "#/$defs/ts"
    },
    "after": {
     "anyOf": [
      {
       "type": "null"
      },
      {
       "$ref": "#/$defs/ts"
      }
     ]
    },
    "target_equal": {
     "type": [
      "boolean",
      "null"
     ]
    },
    "nontarget_shows_equal": {
     "type": [
      "boolean",
      "null"
     ]
    },
    "show_count_before": {
     "type": "integer"
    },
    "show_count_after": {
     "type": [
      "integer",
      "null"
     ]
    },
    "operator_count_before": {
     "type": "integer"
    },
    "operator_count_after": {
     "type": [
      "integer",
      "null"
     ]
    }
   }
  },
  "mutation": {
   "anyOf": [
    {
     "type": "null"
    },
    {
     "type": "object",
     "additionalProperties": false,
     "required": [
      "path",
      "method_id",
      "variable_changed",
      "splice_kind",
      "changes",
      "advance",
      "other_xrefs_changed_live",
      "other_xrefs_changed_semantic",
      "other_xrefs_reserialized",
      "wrapper_bytes_unchanged",
      "new_objects_after_save",
      "new_objects_all_xref",
      "saved_with",
      "output_sha256"
     ],
     "properties": {
      "path": {
       "enum": [
        "product_commit",
        "experiment",
        "canary"
       ]
      },
      "method_id": {
       "enum": [
        "M2_COMMIT",
        "E_STR",
        "E_KERN",
        "E_F1",
        "E_F2I",
        "E_F2R",
        "E_F2G",
        "E_F2K",
        "E_F3",
        "E_F3S",
        "E_F17",
        "CANARY"
       ]
      },
      "variable_changed": {
       "type": "string",
       "minLength": 1
      },
      "splice_kind": {
       "enum": [
        "string_token",
        "whole_operator",
        "tj_item",
        "tj_run",
        "string_fragment",
        "fragment_split",
        "canary"
       ]
      },
      "changes": {
       "type": "array",
       "minItems": 1,
       "items": {
        "type": "object",
        "additionalProperties": false,
        "required": [
         "stream_xref",
         "start",
         "end_old",
         "end_new",
         "token_aligned",
         "old_operand_bytes_hex",
         "old_operand_sha256",
         "new_operand_bytes_hex",
         "new_operand_token_kinds",
         "old_stream_sha256",
         "new_stream_sha256"
        ],
        "properties": {
         "stream_xref": {
          "type": "integer"
         },
         "start": {
          "type": "integer"
         },
         "end_old": {
          "type": "integer"
         },
         "end_new": {
          "type": "integer"
         },
         "token_aligned": {
          "type": "boolean"
         },
         "old_operand_bytes_hex": {
          "type": [
           "string",
           "null"
          ],
          "pattern": "^([0-9A-F]{2})*$"
         },
         "old_operand_sha256": {
          "$ref": "#/$defs/hex64"
         },
         "new_operand_bytes_hex": {
          "type": "string",
          "pattern": "^([0-9A-F]{2})*$"
         },
         "new_operand_token_kinds": {
          "type": "array",
          "items": {
           "type": "string"
          }
         },
         "old_stream_sha256": {
          "$ref": "#/$defs/hex64"
         },
         "new_stream_sha256": {
          "$ref": "#/$defs/hex64"
         }
        }
       }
      },
      "advance": {
       "anyOf": [
        {
         "$ref": "#/$defs/advance"
        },
        {
         "type": "array",
         "minItems": 1,
         "items": {
          "$ref": "#/$defs/advance"
         }
        }
       ]
      },
      "other_xrefs_changed_live": {
       "type": "array",
       "items": {
        "type": "integer"
       }
      },
      "other_xrefs_changed_semantic": {
       "type": "array",
       "items": {
        "type": "integer"
       }
      },
      "other_xrefs_reserialized": {
       "type": "array",
       "items": {
        "type": "integer"
       }
      },
      "wrapper_bytes_unchanged": {
       "type": [
        "boolean",
        "null"
       ]
      },
      "new_objects_after_save": {
       "type": "array",
       "items": {
        "type": "integer"
       }
      },
      "new_objects_all_xref": {
       "type": "boolean"
      },
      "saved_with": {
       "enum": [
        "saveIncr",
        "save_full"
       ]
      },
      "output_sha256": {
       "$ref": "#/$defs/hex64"
      }
     }
    }
   ]
  },
  "growth_zone": {
   "type": "object",
   "additionalProperties": false,
   "required": [
    "applicable",
    "direction",
    "region_visual",
    "region_dict",
    "background_bbox_visual",
    "background_rgb",
    "probe_regions_px_96dpi",
    "probe_regions_failed",
    "raster_proof",
    "gate_detail",
    "before_glyph_bboxes_intersecting",
    "before_drawings_intersecting_bbox",
    "before_drawings_not_provably_clear",
    "stroke_proof",
    "before_images_intersecting",
    "sh_operator_present",
    "files"
   ],
   "properties": {
    "applicable": {
     "type": "boolean"
    },
    "direction": {
     "enum": [
      "right",
      "left",
      "down",
      "up",
      null
     ]
    },
    "region_visual": {
     "anyOf": [
      {
       "type": "null"
      },
      {
       "$ref": "#/$defs/num4"
      }
     ]
    },
    "region_dict": {
     "anyOf": [
      {
       "type": "null"
      },
      {
       "$ref": "#/$defs/num4"
      }
     ]
    },
    "background_bbox_visual": {
     "anyOf": [
      {
       "type": "null"
      },
      {
       "$ref": "#/$defs/num4"
      }
     ]
    },
    "background_rgb": {
     "anyOf": [
      {
       "type": "null"
      },
      {
       "$ref": "#/$defs/num3"
      }
     ]
    },
    "probe_regions_px_96dpi": {
     "anyOf": [
      {
       "type": "null"
      },
      {
       "type": "array",
       "items": {
        "$ref": "#/$defs/int4"
       }
      }
     ]
    },
    "probe_regions_failed": {
     "type": [
      "integer",
      "null"
     ]
    },
    "raster_proof": {
     "enum": [
      "pass",
      "fail",
      null
     ]
    },
    "gate_detail": {
     "type": [
      "string",
      "null"
     ]
    },
    "before_glyph_bboxes_intersecting": {
     "type": [
      "integer",
      "null"
     ]
    },
    "before_drawings_intersecting_bbox": {
     "type": [
      "integer",
      "null"
     ]
    },
    "before_drawings_not_provably_clear": {
     "type": [
      "integer",
      "null"
     ]
    },
    "stroke_proof": {
     "enum": [
      "not_needed",
      "clear",
      "failed",
      null
     ]
    },
    "before_images_intersecting": {
     "type": [
      "integer",
      "null"
     ]
    },
    "sh_operator_present": {
     "type": [
      "boolean",
      "null"
     ]
    },
    "files": {
     "type": "array",
     "items": {
      "type": "string",
      "pattern": "render-[A-Za-z0-9_.-]+\\.png$"
     }
    }
   }
  },
  "neighbours": {
   "type": "object",
   "additionalProperties": false,
   "required": [
    "pairing_rule",
    "glyphs_total",
    "glyphs_checked",
    "unpaired_glyphs",
    "target_glyphs_before",
    "target_glyphs_after",
    "target_origin_delta_pt",
    "untouched_max_origin_delta_pt",
    "inshow_successor_max_origin_delta_pt",
    "gid_mismatches",
    "ink_mismatches",
    "overlap_glyphs",
    "halo_shadowed_glyphs",
    "records_file"
   ],
   "properties": {
    "pairing_rule": {
     "const": "texttrace_order_origin_match/v1"
    },
    "glyphs_total": {
     "type": "integer"
    },
    "glyphs_checked": {
     "type": [
      "integer",
      "null"
     ]
    },
    "unpaired_glyphs": {
     "type": [
      "integer",
      "null"
     ]
    },
    "target_glyphs_before": {
     "type": "integer"
    },
    "target_glyphs_after": {
     "type": [
      "integer",
      "null"
     ]
    },
    "target_origin_delta_pt": {
     "type": [
      "number",
      "null"
     ]
    },
    "untouched_max_origin_delta_pt": {
     "type": [
      "number",
      "null"
     ]
    },
    "inshow_successor_max_origin_delta_pt": {
     "type": [
      "number",
      "null"
     ]
    },
    "gid_mismatches": {
     "type": [
      "integer",
      "null"
     ]
    },
    "ink_mismatches": {
     "type": [
      "integer",
      "null"
     ]
    },
    "overlap_glyphs": {
     "type": [
      "integer",
      "null"
     ]
    },
    "halo_shadowed_glyphs": {
     "type": [
      "integer",
      "null"
     ]
    },
    "records_file": {
     "type": "string",
     "pattern": "^cases/[A-Za-z0-9_-]+/neighbours\\.json$"
    }
   }
  },
  "glyph_identity": {
   "type": "array",
   "items": {
    "type": "object",
    "additionalProperties": false,
    "required": [
     "index",
     "char",
     "is_space",
     "code_bytes_hex",
     "gid_after",
     "has_outline",
     "consistency",
     "gid_equals_consistency",
     "independent_leg"
    ],
    "properties": {
     "index": {
      "type": "integer"
     },
     "char": {
      "type": "string"
     },
     "is_space": {
      "type": "boolean"
     },
     "code_bytes_hex": {
      "type": "string",
      "pattern": "^([0-9A-F]{2})+$"
     },
     "gid_after": {
      "type": [
       "integer",
       "null"
      ]
     },
     "has_outline": {
      "type": [
       "boolean",
       "null"
      ]
     },
     "consistency": {
      "anyOf": [
       {
        "type": "null"
       },
       {
        "type": "object",
        "additionalProperties": false,
        "required": [
         "show_seq",
         "char_index",
         "gid",
         "selected_by"
        ],
        "properties": {
         "show_seq": {
          "type": "integer"
         },
         "char_index": {
          "type": "integer"
         },
         "gid": {
          "type": "integer"
         },
         "selected_by": {
          "enum": [
           "glyph_name",
           "cmap_31_reverse",
           "standard_14_table",
           "cid_tounicode"
          ]
         }
        }
       }
      ]
     },
     "gid_equals_consistency": {
      "type": [
       "boolean",
       "null"
      ]
     },
     "independent_leg": {
      "type": "object",
      "additionalProperties": false,
      "required": [
       "kind",
       "value",
       "equals_char",
       "gid",
       "gid_equals_after"
      ],
      "properties": {
       "kind": {
        "enum": [
         "cid_tounicode",
         "glyph_name_agl",
         "cmap_31_reverse",
         "standard_14_table",
         "none"
        ]
       },
       "value": {
        "type": [
         "string",
         "null"
        ]
       },
       "equals_char": {
        "type": [
         "boolean",
         "null"
        ]
       },
       "gid": {
        "type": [
         "integer",
         "null"
        ]
       },
       "gid_equals_after": {
        "type": [
         "boolean",
         "null"
        ]
       }
      }
     }
    }
   }
  },
  "extraction": {
   "type": "object",
   "additionalProperties": false,
   "required": [
    "after_text_at_target",
    "equals_replacement",
    "old_text_remains_at_target",
    "nontarget_text_changes"
   ],
   "properties": {
    "after_text_at_target": {
     "type": [
      "string",
      "null"
     ]
    },
    "equals_replacement": {
     "type": [
      "boolean",
      "null"
     ]
    },
    "old_text_remains_at_target": {
     "type": [
      "boolean",
      "null"
     ]
    },
    "nontarget_text_changes": {
     "type": [
      "integer",
      "null"
     ]
    }
   }
  },
  "render": {
   "type": "object",
   "additionalProperties": false,
   "required": [
    "mask_rule",
    "halo_area_pt2",
    "mupdf",
    "poppler",
    "live_vs_reopened_changed_px"
   ],
   "properties": {
    "mask_rule": {
     "const": "union(target_bbox_visual, after_bbox_visual) +-3pt, compared at 2x"
    },
    "halo_area_pt2": {
     "type": [
      "number",
      "null"
     ]
    },
    "mupdf": {
     "$ref": "#/$defs/renderer"
    },
    "poppler": {
     "$ref": "#/$defs/renderer"
    },
    "live_vs_reopened_changed_px": {
     "type": [
      "integer",
      "null"
     ]
    }
   }
  },
  "save_reopen": {
   "type": "object",
   "additionalProperties": false,
   "required": [
    "method",
    "page_count_equal",
    "new_objects_subset_xref",
    "reopened_text_at_target_equals_replacement",
    "text_state_equal",
    "glyph_identity_equal",
    "source_sha256_unchanged"
   ],
   "properties": {
    "method": {
     "type": "string"
    },
    "page_count_equal": {
     "type": [
      "boolean",
      "null"
     ]
    },
    "new_objects_subset_xref": {
     "type": [
      "boolean",
      "null"
     ]
    },
    "reopened_text_at_target_equals_replacement": {
     "type": [
      "boolean",
      "null"
     ]
    },
    "text_state_equal": {
     "type": [
      "boolean",
      "null"
     ]
    },
    "glyph_identity_equal": {
     "type": [
      "boolean",
      "null"
     ]
    },
    "source_sha256_unchanged": {
     "type": "boolean"
    }
   }
  },
  "phases": {
   "type": "object",
   "additionalProperties": false,
   "required": [
    "probe",
    "structure",
    "growth_zone",
    "render_mupdf",
    "render_poppler",
    "neighbours",
    "glyph_identity",
    "extraction",
    "save_reopen"
   ],
   "properties": {
    "probe": {
     "$ref": "#/$defs/phase"
    },
    "structure": {
     "$ref": "#/$defs/phase"
    },
    "growth_zone": {
     "$ref": "#/$defs/phase"
    },
    "render_mupdf": {
     "$ref": "#/$defs/phase"
    },
    "render_poppler": {
     "$ref": "#/$defs/phase"
    },
    "neighbours": {
     "$ref": "#/$defs/phase"
    },
    "glyph_identity": {
     "$ref": "#/$defs/phase"
    },
    "extraction": {
     "$ref": "#/$defs/phase"
    },
    "save_reopen": {
     "$ref": "#/$defs/phase"
    }
   }
  },
  "observation": {
   "type": "string"
  },
  "hypotheses": {
   "type": "array",
   "maxItems": 3,
   "items": {
    "type": "object",
    "additionalProperties": false,
    "required": [
     "id",
     "statement",
     "falsification",
     "result"
    ],
    "properties": {
     "id": {
      "type": "string"
     },
     "statement": {
      "type": "string"
     },
     "falsification": {
      "type": "string"
     },
     "result": {
      "enum": [
       "supported",
       "refuted",
       "insufficient_evidence",
       "pending"
      ]
     }
    }
   }
  },
  "next_check": {
   "type": "string"
  },
  "attempts": {
   "type": "array",
   "maxItems": 3,
   "items": {
    "type": "object",
    "additionalProperties": false,
    "required": [
     "n",
     "method_id",
     "variable_changed",
     "outcome",
     "new_evidence"
    ],
    "properties": {
     "n": {
      "type": "integer"
     },
     "method_id": {
      "type": "string"
     },
     "variable_changed": {
      "type": "string"
     },
     "outcome": {
      "type": "string"
     },
     "new_evidence": {
      "type": "boolean"
     }
    }
   }
  },
  "peel_chain": {
   "type": "array",
   "maxItems": 3,
   "items": {
    "type": "object",
    "additionalProperties": false,
    "required": [
     "removed_feature",
     "probe_reason_after"
    ],
    "properties": {
     "removed_feature": {
      "type": "string"
     },
     "probe_reason_after": {
      "type": [
       "string",
       "null"
      ]
     }
    }
   }
  },
  "code_revision": {
   "type": "object",
   "additionalProperties": false,
   "required": [
    "git_head",
    "tracked_diff_empty",
    "dirty",
    "dirty_diff_id"
   ],
   "properties": {
    "git_head": {
     "type": "string",
     "pattern": "^[0-9a-f]{40}$"
    },
    "tracked_diff_empty": {
     "const": true
    },
    "dirty": {
     "type": "boolean"
    },
    "dirty_diff_id": {
     "type": "string",
     "pattern": "^([0-9a-f]{64}|unknown)$"
    },
    "runner_sha256": {
     "type": "string",
     "pattern": "^[0-9a-f]{64}$"
    }
   }
  },
  "tool_versions": {
   "type": "object",
   "additionalProperties": false,
   "required": [
    "python",
    "pymupdf",
    "mupdf",
    "numpy",
    "pillow",
    "fonttools",
    "pdftoppm"
   ],
   "properties": {
    "python": {
     "type": "string"
    },
    "pymupdf": {
     "type": "string",
     "pattern": "^1\\.27\\."
    },
    "mupdf": {
     "type": "string"
    },
    "numpy": {
     "type": "string"
    },
    "pillow": {
     "type": "string"
    },
    "fonttools": {
     "type": "string"
    },
    "pdftoppm": {
     "type": [
      "string",
      "null"
     ]
    }
   }
  },
  "command": {
   "type": "string",
   "pattern": "^\\.venv\\\\Scripts\\\\python\\.exe -B "
  },
  "timestamp": {
   "type": "string",
   "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}[+-][0-9]{2}:?[0-9]{2}$"
  },
  "artifacts": {
   "type": "object",
   "additionalProperties": false,
   "required": [
    "dir",
    "files"
   ],
   "properties": {
    "dir": {
     "type": "string",
     "pattern": "^cases/[A-Za-z0-9_-]+/$"
    },
    "files": {
     "type": "array",
     "items": {
      "type": "string",
      "pattern": "^(cases/[A-Za-z0-9_-]+/(render-[A-Za-z0-9_.-]+\\.png|[A-Za-z0-9_.-]+\\.json)|candidates/[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+\\.pdf)$"
     }
    }
   }
  },
  "limits": {
   "type": "array",
   "items": {
    "type": "string"
   }
  },
  "redaction": {
   "type": "object",
   "additionalProperties": false,
   "required": [
    "applied",
    "entries",
    "scan"
   ],
   "properties": {
    "applied": {
     "type": "boolean"
    },
    "entries": {
     "type": "array",
     "items": {
      "type": "object",
      "additionalProperties": false,
      "required": [
       "json_pointer",
       "placeholder",
       "sha256_utf8"
      ],
      "properties": {
       "json_pointer": {
        "type": "string"
       },
       "placeholder": {
        "type": "string",
        "pattern": "^\\[PLACEHOLDER_[0-9]+\\]$"
       },
       "sha256_utf8": {
        "$ref": "#/$defs/hex64"
       }
      }
     }
    },
    "scan": {
     "type": "object",
     "additionalProperties": false,
     "required": [
      "client_strings_left",
      "machine_paths_left",
      "language_warnings"
     ],
     "properties": {
      "client_strings_left": {
       "type": "integer",
       "minimum": 0
      },
      "machine_paths_left": {
       "type": "integer",
       "minimum": 0
      },
      "language_warnings": {
       "type": "integer",
       "minimum": 0
      }
     }
    }
   }
  }
 },
 "$defs": {
  "hex64": {
   "type": "string",
   "pattern": "^[0-9a-f]{64}$"
  },
  "num2": {
   "type": "array",
   "items": {
    "type": "number"
   },
   "minItems": 2,
   "maxItems": 2
  },
  "num3": {
   "type": "array",
   "items": {
    "type": "number"
   },
   "minItems": 3,
   "maxItems": 3
  },
  "num4": {
   "type": "array",
   "items": {
    "type": "number"
   },
   "minItems": 4,
   "maxItems": 4
  },
  "int4": {
   "type": "array",
   "items": {
    "type": "integer"
   },
   "minItems": 4,
   "maxItems": 4
  },
  "num6": {
   "type": "array",
   "items": {
    "type": "number"
   },
   "minItems": 6,
   "maxItems": 6
  },
  "phase": {
   "type": "object",
   "additionalProperties": false,
   "required": [
    "result",
    "detail",
    "evidence"
   ],
   "properties": {
    "result": {
     "enum": [
      "pass",
      "fail",
      "not_run",
      "blocked"
     ]
    },
    "detail": {
     "type": "string"
    },
    "evidence": {
     "type": "array",
     "items": {
      "type": "string"
     }
    }
   }
  },
  "advance": {
   "type": "object",
   "additionalProperties": false,
   "required": [
    "K_written",
    "K_sum",
    "K_disp_engine",
    "K_disp_hand",
    "abs_diff_written_vs_sum_engine",
    "abs_diff_engine_hand",
    "displacement",
    "adv_old_text_space",
    "adv_new_text_space",
    "growth_pt",
    "advance_tolerance",
    "Tfs",
    "Th",
    "Tc",
    "Tw",
    "char_count_old",
    "char_count_new",
    "space_count",
    "advance_source",
    "advance_function",
    "internal_kerns_dropped",
    "border_kerns_byte_identical"
   ],
   "properties": {
    "K_written": {
     "type": [
      "number",
      "null"
     ]
    },
    "K_sum": {
     "type": [
      "number",
      "null"
     ]
    },
    "K_disp_engine": {
     "type": [
      "number",
      "null"
     ]
    },
    "K_disp_hand": {
     "type": [
      "number",
      "null"
     ]
    },
    "abs_diff_written_vs_sum_engine": {
     "type": [
      "number",
      "null"
     ]
    },
    "abs_diff_engine_hand": {
     "type": [
      "number",
      "null"
     ]
    },
    "displacement": {
     "type": "number"
    },
    "displacement_ink": {
     "type": "number"
    },
    "adv_old_text_space": {
     "type": "number"
    },
    "adv_new_text_space": {
     "type": "number"
    },
    "growth_pt": {
     "type": "number",
     "minimum": 0
    },
    "advance_tolerance": {
     "type": "number",
     "minimum": 0
    },
    "Tfs": {
     "type": "number"
    },
    "Th": {
     "type": "number"
    },
    "Tc": {
     "type": "number"
    },
    "Tw": {
     "type": "number"
    },
    "char_count_old": {
     "type": "integer"
    },
    "char_count_new": {
     "type": "integer"
    },
    "space_count": {
     "type": "integer"
    },
    "advance_source": {
     "enum": [
      "W",
      "DW",
      "Widths",
      "face",
      "type3_widths"
     ]
    },
    "advance_function": {
     "type": "string"
    },
    "internal_kerns_dropped": {
     "type": "array",
     "items": {
      "type": "number"
     }
    },
    "border_kerns_byte_identical": {
     "type": [
      "boolean",
      "null"
     ]
    }
   }
  },
  "probe_result": {
   "type": "object",
   "additionalProperties": false,
   "required": [
    "result",
    "tier",
    "reason",
    "detail",
    "exception_type",
    "prepared"
   ],
   "properties": {
    "result": {
     "enum": [
      "prepared",
      "rejected",
      "exception",
      "not_run"
     ]
    },
    "tier": {
     "enum": [
      0,
      1,
      null
     ]
    },
    "reason": {
     "type": [
      "string",
      "null"
     ]
    },
    "detail": {
     "type": [
      "string",
      "null"
     ]
    },
    "exception_type": {
     "type": [
      "string",
      "null"
     ]
    },
    "prepared": {
     "anyOf": [
      {
       "type": "null"
      },
      {
       "type": "object",
       "additionalProperties": false,
       "required": [
        "stream_xref",
        "replacement_start",
        "replacement_end",
        "binding_op_start",
        "binding_op_end",
        "font_xref",
        "source_advance",
        "replacement_advance",
        "kern_adjustment",
        "verify_bbox_page",
        "background_bbox_page"
       ],
       "properties": {
        "stream_xref": {
         "type": "integer"
        },
        "replacement_start": {
         "type": "integer"
        },
        "replacement_end": {
         "type": "integer"
        },
        "binding_op_start": {
         "type": "integer"
        },
        "binding_op_end": {
         "type": "integer"
        },
        "font_xref": {
         "type": "integer"
        },
        "source_advance": {
         "type": "number"
        },
        "replacement_advance": {
         "type": "number"
        },
        "kern_adjustment": {
         "type": [
          "number",
          "null"
         ]
        },
        "verify_bbox_page": {
         "anyOf": [
          {
           "type": "null"
          },
          {
           "$ref": "#/$defs/num4"
          }
         ]
        },
        "background_bbox_page": {
         "anyOf": [
          {
           "type": "null"
          },
          {
           "$ref": "#/$defs/num4"
          }
         ]
        }
       }
      }
     ]
    }
   }
  },
  "colour": {
   "type": "object",
   "additionalProperties": false,
   "required": [
    "op",
    "operands_raw",
    "is_pattern"
   ],
   "properties": {
    "op": {
     "type": [
      "string",
      "null"
     ]
    },
    "operands_raw": {
     "type": [
      "string",
      "null"
     ]
    },
    "is_pattern": {
     "type": "boolean"
    }
   }
  },
  "ts": {
   "type": "object",
   "additionalProperties": false,
   "required": [
    "Tf",
    "Tm",
    "CTM",
    "det_sign",
    "Tz",
    "Tc",
    "Tw",
    "Ts",
    "TL",
    "Tr",
    "fill_colour_op",
    "stroke_colour_op",
    "line_width",
    "extgstate_names",
    "wrapper_stack",
    "q_depth",
    "in_bt",
    "origin_user",
    "origin_reliable"
   ],
   "properties": {
    "Tf": {
     "type": "object",
     "additionalProperties": false,
     "required": [
      "resource",
      "size"
     ],
     "properties": {
      "resource": {
       "type": "string"
      },
      "size": {
       "type": "number"
      }
     }
    },
    "Tm": {
     "$ref": "#/$defs/num6"
    },
    "CTM": {
     "$ref": "#/$defs/num6"
    },
    "det_sign": {
     "enum": [
      "+",
      "-"
     ]
    },
    "Tz": {
     "type": "number"
    },
    "Tc": {
     "type": "number"
    },
    "Tw": {
     "type": "number"
    },
    "Ts": {
     "type": "number"
    },
    "TL": {
     "type": "number"
    },
    "Tr": {
     "type": "integer"
    },
    "fill_colour_op": {
     "$ref": "#/$defs/colour"
    },
    "stroke_colour_op": {
     "$ref": "#/$defs/colour"
    },
    "line_width": {
     "type": [
      "number",
      "null"
     ]
    },
    "extgstate_names": {
     "type": "array",
     "items": {
      "type": "string"
     }
    },
    "wrapper_stack": {
     "type": "array",
     "items": {
      "type": "object",
      "additionalProperties": false,
      "required": [
       "kind",
       "tag",
       "class_slug",
       "props_kind",
       "props_name",
       "props_keys",
       "structelem_keys",
       "stream_xref",
       "start",
       "end"
      ],
      "properties": {
       "kind": {
        "enum": [
         "BDC",
         "BMC"
        ]
       },
       "tag": {
        "type": "string"
       },
       "class_slug": {
        "type": "string"
       },
       "props_kind": {
        "enum": [
         "none",
         "name",
         "dict",
         "unparsed"
        ]
       },
       "props_name": {
        "type": [
         "string",
         "null"
        ]
       },
       "props_keys": {
        "type": "array",
        "items": {
         "type": "string"
        }
       },
       "structelem_keys": {
        "type": [
         "array",
         "null"
        ],
        "items": {
         "type": "string"
        }
       },
       "stream_xref": {
        "type": "integer"
       },
       "start": {
        "type": "integer"
       },
       "end": {
        "type": [
         "integer",
         "null"
        ]
       }
      }
     }
    },
    "q_depth": {
     "type": "integer"
    },
    "in_bt": {
     "type": "boolean"
    },
    "origin_user": {
     "$ref": "#/$defs/num2"
    },
    "origin_reliable": {
     "type": "boolean"
    }
   }
  },
  "renderer": {
   "type": "object",
   "additionalProperties": false,
   "required": [
    "status",
    "version",
    "crop_zoom",
    "target_changed_px",
    "fullpage_zoom",
    "nontarget_changed_px",
    "control_rerender_changed_px",
    "files"
   ],
   "properties": {
    "status": {
     "enum": [
      "pass",
      "fail",
      "not_run",
      "blocked"
     ]
    },
    "version": {
     "type": [
      "string",
      "null"
     ]
    },
    "crop_zoom": {
     "type": "number",
     "minimum": 6
    },
    "target_changed_px": {
     "type": [
      "integer",
      "null"
     ]
    },
    "fullpage_zoom": {
     "type": "number",
     "minimum": 2
    },
    "nontarget_changed_px": {
     "type": [
      "integer",
      "null"
     ]
    },
    "control_rerender_changed_px": {
     "type": [
      "integer",
      "null"
     ]
    },
    "files": {
     "type": "array",
     "items": {
      "type": "string",
      "pattern": "render-[A-Za-z0-9_.-]+\\.png$"
     }
    }
   }
  }
 }
}
```

**schema 表達不了、由驗證器做的交叉欄位規則（違反任一 → 整案退件）：**
- `mutation.splice_kind == "canary"` ⇔ `kind == "canary"`；`mutation.path == "canary"` ⇔ `kind == "canary"`；`mutation.method_id == "CANARY"` ⇔ `kind == "canary"`。
- **kind ⇔ class_id**：kind=canary ⇔ class_id 以 `CANARY_` 開頭；kind=control ⇔ class_id 以 `CTRL_` 開頭；kind ∈ {positive, negative, census} ⇔ class_id 是 F 類（F30B…F6）或 `OUT`（只准 census）。PARENT_SUMMARY 的 `per_class` 只計 kind ∈ {positive, negative, census}。
- `splice_kind ≠ canary` 時 `len(mutation.changes) == 1`。
- **目標粒度（v4，V12）：** `item_range_bounds`（`brief_revision >= 3`）——`item_range` 非 null 時必須是 TJ 上的 `0 ≤ i0 < i1 ≤ array_item_count`，F3 必須 `i1 == i0 + 1`；TJ 上的 F3 缺 `item_range` 也算；`item_range_span`（`brief_revision >= 4`）——`changes[0].old_operand_bytes_hex` 裡的 string token 數必須等於 `i1 − i0`，`tj_item`／`tj_run` 的 old operand 首尾必須是 string token（border kern 不在 run 內）；非公開列這一條由 rederive 在原檔上重 lex（驗證器列為 unverifiable）；`show_text_sha256_required`、`show_text_sha256_mismatch`（`brief_revision >= 4`）——欄位必填、必須是 64 位小寫 hex、等於 `source_decode.latin1_sha256`，整個 show 為目標時也等於 `original_sha256`。`whole_show_view_required`（`brief_revision >= 4`）——切片目標（`item_range` 或 `byte_range_in_item` 非 null）的列，`probe.whole_show_max_tier_1` 必須是非 null 的 probe 結果（上面 M1 的整個 show 第二視角），缺鍵或 null 都退件；只有整個 show 為目標的列寫 null。`brief_revision < 4` 的列不得帶 `corpus_case.show_text_sha256` 或 `probe.whole_show_max_tier_1`（`schema_additional`）。
- **幾何欄位（v4，V13；`brief_revision >= 4`）：** `geometry_on_untracked_origin`——`origin_reliable == false` 的列只要有任何一個幾何欄位非 null；`geometry_null_on_tracked_origin`——`origin_reliable != false` 的列有任何一個幾何欄位是 null；`geometry_partly_null`——三個欄位有的 null 有的不是；`geometry_null_without_limit`——null 的列 `limits[]` 沒有任何非空字串。`brief_revision < 4` 的列幾何欄位為 null 是 `schema_type`。rederive 對所有版本的列都重算：untracked origin 上的非 null 幾何是 `geometry_on_untracked_origin` 分歧。
- `mutation.advance` 每個 mutation 必填（null 不合法）；為陣列只允許 splice_kind=`tj_run` 且目標橫跨多個以字間空白切開的 run（本輪不預期出現）。**K token 規則依路徑**：`path=product_commit` 且 `probe.commit.tier == 1` → `K_written` 必須非 null；`path=product_commit` 且 `tier == 0` → `K_written`、`K_sum`、`K_disp_engine`、`K_disp_hand` 全 null，**不論 Δ**（Tier 0 容許 `|Δ| ≤ advance_tolerance` 且從不寫 number token，`plan.py:2060`、`:2106-2110`；實測 4 個 Tier 0 commit 的 Δ 都恰好是 0）；`path ∈ {experiment, canary}` → `|adv_new − adv_old| > advance.advance_tolerance` 時 `K_written` 必須非 null（任何改變 advance 的 splice 都必須寫 K token；「K 為 null、after bbox 卻變寬」是退件形狀），`|Δ| ≤ tolerance` 視為等寬。`advance.advance_tolerance` 由驗證器重算：`advance_source ∈ {W, DW, Widths, type3_widths}` → `max(1e-9·Tfs, 1e-9)`；`face` → `max(1e-3·Tfs, 1e-4)`（`plan.py:101-102`）。新 operand 沒有 number token 時 `K_written`、`K_sum`、`K_disp_engine`、`K_disp_hand` 都必須是 null。**v3（`brief_revision >= 3`，R7-1）：`advance.displacement_ink` 必填**，且 = `(adv_new_text_space − adv_old_text_space) + K_sum·Tfs/1000`（1e-6）。缺這個欄位 → `displacement_ink_missing`；值不符 → `displacement_ink_mismatch`。**驗證器用的 K_sum 依 splice_kind**：`splice_kind ≠ tj_run` → 一律 0.0（不看你寫的 `K_sum`，所以 `splice_kind ∉ {tj_item, tj_run}` 時它必須等於 Δ）；`tj_run` 且 `old_operand_bytes_hex` 在紀錄裡（public／synthetic）→ 從舊 operand 的數字 token 重算；`tj_run` 且舊 operand 已 null（非公開列）→ 用你寫的 `K_sum` 並記 `k_sum_unverified`（unverifiable，不是 violation；rederive 在本機原檔上核對後關掉），而你寫的 `K_sum` 也是 null 時**不視為 0.0**：structure 與 growth_zone phase 記 undecided `ink_kerns_unknown`、該案不算 pass；`brief_revision 2` 的列沒有這個欄位（schema 的 `advance` 把它列在 properties、不列在 required，由驗證器依 brief_revision 要求）。
- **advance 的來源欄位**（H1）：`advance.advance_function` 依 `corpus_case.font_kind` 固定——`simple` → `plan._advance/FontCapability.string_width`，`type0` → `IdentityHCidCapability.advance_points`；`advance_source` 依 `font_kind` 限制——`type0` → {W, DW}，`simple` → {Widths, face}；`type3_widths` 不可能出現在有 mutation 的紀錄（Type3 只做 census）。`path=product_commit` 且 **`probe.commit.tier == 1`** 時 `adv_old_text_space`／`adv_new_text_space` 必須等於 `probe.max_tier_1.prepared.source_advance`／`replacement_advance`（容差 `advance_tolerance`）；**Tier 0 不適用這條（v3 (b)）**——`PreparedEdit` 把 `source_advance`／`replacement_advance` 留在 dataclass 預設值 0.0（`plan.py:165-166`；`_build_tier0` 不填，只有 `_build_tier1` 填），所以 Tier 0 列的 `prepared.source_advance`／`replacement_advance` 照抄 0.0，`advance.adv_old_text_space`／`adv_new_text_space` 是用同一組產品函式（`advance_points`／`plan._advance`）實測的等寬值（v2 那句「adv 必須等於 prepared.source_advance」對 Tier 0 是錯的；驗證器本來就只對 tier 1 檢查，rederive 對兩個 tier 都重算 adv_*）。這些只是算術交叉檢查；adv 的**值**由 Claude 端的 rederive 用產品函式在本機原檔上重算（§0、§5.2），`advance_source` 也由 `capability.advance_source` 重算，不符 → `quarantined: remeasure`。
- `source.provenance ∉ {public, synthetic}` 時：`corpus_case.original`、`source_decode.latin1`、`source_decode.independent`、每個 `changes[].old_operand_bytes_hex` 都必須是 null，對應的 sha256 欄位必填（violation `redaction_null_required`；**沒有 calibration-row 例外**——class_id ∈ {CTRL_POS_T0, CTRL_POS_T1, CTRL_NEG} 與六個 canary 的 `corpus_case.original` 一樣必須 null，§2.1／§5.4 的 calibration-row exemption 只豁免第二層掃描，不豁免這條）；**hvac／ecc 的 provenance 必須是 `proprietary`（§3.0）——但這不是驗證器規則**：validate 對 provenance 值只做 schema 詞彙與 null 規則，寫成 `local_unrecorded` 會通過 validate 與 self-check，到 Claude 端 rederive 才整案 `quarantined: provenance_unverified`；`source.relative_path` 在 proprietary 與 synthetic 時必須是 null；**v4：** public 與 local_unrecorded 時必須是 `test_files/…` 路徑字串（`relative_path_required`，只對 `brief_revision >= 4`），而且 `slug` 必須等於它的檔名主幹經 `_slugify` 的結果（`slug_not_derived`，只對 `brief_revision >= 4`）。
- **`growth_zone.applicable`（與 K 是否存在無關、與 kind 無關——positive、control、canary 一體適用）：** `mutation=null`（CTRL_NEG、CTRL_SYN_T1、negative、census）→ `applicable=false`、其餘 growth_zone 欄位全 null、phase result=`not_run`、detail="no mutation"，本條其餘規則跳過；`path=product_commit` → `applicable` ⇔ `probe.commit.tier == 1` 且 `adv_new_text_space > adv_old_text_space`（鏡像產品 `PreparedEdit.has_ink_growth`：`verify_bbox_page` 只由 `_build_tier1` 設定，`plan.py:2596`，而 `_grown_verify_bbox` 在 growth ≤ 0 時原樣回傳 target，`plan.py:2393-2394`——所以沒有增長時產品的 verify 框就是 target 框；Tier 0 的 product commit 一律 false）；`path ∈ {experiment, canary}` → `applicable` ⇔ `displacement_ink > advance.advance_tolerance`（v3，§3.3 R7-1；`brief_revision 2` 的列仍是 `adv_new − adv_old`）。**bbox 交叉檢查（所有 bbox 比較一律每分量 1e-3，float32 往返的 2.4e-5 在容差內；reason／tier／K 才是 1e-6）：** `applicable=false` 時，以產品 `_growth_zone_rect(target_bbox_visual, after_bbox_visual)` 算出的主增長邊延伸量必須 ≤ 0.5 pt（產品 own-char 邊界容差，`verify.py:1467-1488`；`_growth_zone_rect` 在延伸 ≤ 0 時回傳 None，`verify.py:1155-1156`，**None 視為延伸量 0**），否則 **growth_zone phase fail**（reason `after_exceeds_target`，phase detail 寫出主邊延伸量 pt；`brief_revision 2` 是退件 violation `growth_after_exceeds_target`，v3 改為 phase fail、不是退件，§8 (n)：紀錄誠實，after 的 ink 落在沒有被證明空白的帶子裡是保真事實，status 依 §5.3 走規則 7／8）；`applicable=true` 時 `target.verify_bbox_visual` 必須等於 `target_bbox_visual` 在 `direction` 側延伸 `growth_pt`（1e-3；product_commit 列照抄 `prepared.verify_bbox_page`，experiment／canary 列自己算公式），`region_visual` 必須等於 `_growth_zone_rect(target_bbox_visual, verify_bbox_visual)`（1e-3），`direction` 必須是其主邊，`growth_zone.background_bbox_visual` 必須等於 `transforms.map_text_quad_to_visual(page, show.tm, show.ctm, (x_pre*Th, -0.35*Tfs, (x_pre + adv_old_text_space - K_inner/1000*Tfs)*Th, Tfs), frame=frame)`（`x_pre`、`K_inner` 的定義在 §5.2 growth_zone 的 `background_bbox_visual` 與 §9 (t)；1e-3；驗證器不重算這個框、列為 unverifiable `background_bbox`，由 rederive 在本機原檔上重算；product_commit 列照抄 `prepared.background_bbox_page`）。**after 不得跑出 verify（H1）：** `applicable=true` 時，`_growth_zone_rect(target_bbox_visual, after_bbox_visual)` 的主邊延伸量（`verify.py:1148-1154` 的 `amount`；None 視為 0）必須 ≤ `_growth_zone_rect(target_bbox_visual, verify_bbox_visual)` 的主邊延伸量 + 0.5 pt（產品 own-char 邊界容差，`verify.py:1467-1478`），否則 growth_zone phase fail（reason `after_exceeds_verify`；v3 不再同時是退件 violation；after 沒有長到宣告的 growth_pt（主邊延伸 ≤ 0，或 < growth_pt − 0.5 pt）→ `after_not_grown`，同樣只是 phase fail）——方向那一半已由上一句釘住（`direction` 是 after 相對 target 的主邊，verify 就是 target 在那一邊的延伸）。`render.halo_area_pt2` 必須等於 `(w_u + 6)·(h_u + 6)`（1e-3），u = `target_bbox_visual ∪ after_bbox_visual`。
- `growth_zone.region_dict` 必須等於 `region_visual × ~frame.quarter_turn`（`frame = transforms.page_visual_frame_or_none(page)`，產品 `_visual_bbox_to_dict_space`；每個分量 1e-3；驗證器在本機原檔上同樣算）；`target_bbox_raw`／`after_bbox_raw` 與對應 `*_visual` 的關係相同。
- `glyph_identity[].independent_leg.gid` 必須等於 `gid_after` 且 ≠ 0（每個 `is_space=false` 的替換字；`gid_equals_after` 只是你的附註，驗證器重算；Type1 的 gid 依 M0 的 fitz 配方由 rederive 重算）。`mutation ≠ null` 時 `len(glyph_identity) == len(corpus_case.replacement)`，而且每筆的 `is_space == corpus_case.replacement[index].isspace()`（`is_space` 不是自由布林：標成空白就跳過 (a)–(c)，所以驗證器重算它）；`mutation=null` 時 `glyph_identity == []`。
- `source.before_pdf_sha256 == source.sha256`，且 `check_artifacts` 重算 `candidates/<case_id>/before.pdf` 的 sha256 必須等於它。
- `mutation.saved_with == "saveIncr"` 是 save_reopen phase pass 的必要條件（§5.2 的 save_reopen 定義在 saveIncr 上；`save_full` 的紀錄 save_reopen 只能是 fail）。
- `source.synthetic_builder` 非 null ⇔ `source.provenance == "synthetic"`；`callable` 必須在 rederive 的白名單（本輪只有 `test_scripts.type0_fixture_builder.build_identity_h_fixture`），`kwargs` 只能是 JSON 純量；CTRL_SYN_* 的值固定為 §2.1 所列。rederive 只 import 白名單 callable 重建，從不執行你的程式。**`provenance == "synthetic"` ⇒ `kind ∈ {control, canary}`**（H4），而且 `class_id ∈ {CTRL_SYN_T0, CTRL_SYN_T1, CANARY_GROWTH}`——只有 `calibration_ref == "synthetic_only"`（§2.3 的 hvac 缺失 fallback）時其他 `CANARY_*` 才可以；kind=positive／negative／census 配 synthetic 一律退件。synthetic 列不算 lineage，`emit_rows` 不從它產生 manifest 列（§3.0）。
- `target.user_unit` 必須等於本機原檔 `frame.user_unit`（`transforms.PageVisualFrame.user_unit`，1e-6）；`target.trm_scale` 必須等於 **baseline row 的 norm** `math.hypot(linear[0], linear[1])`，其中 `linear = transforms.combined_linear(show.tm, show.ctm)`（4 元組 `(a, b, c, d)`，`transforms.py:50`、`:475-484`；產品 `_grown_verify_bbox` 的 `norm`，`plan.py:2396`）（1e-6）。**不是** `hypot(*linear)`：那是四分量的 Frobenius norm，對每個正交等比 show 都是 √2 倍（hvac p4 s11／s26／s161 實測 0.0849 對 0.060，Basis (9)），會把 CTRL_POS_T1 的 `growth_pt` 算成 2.983 pt 而退掉必做的控制組。
- `text_state.*.wrapper_stack[]` 每一項：`props_keys` 必須等於本機原檔 replay 的 `McWrapper.props_dict_keys`（inline dict 的頂層 key；name operand → `[]`），`props_kind`／`props_name` 必須等於 `McWrapper.props_kind`／`props_name`（驗證器在本機原檔上重算；把 /Properties 資源或 OCG 字典的 key 填進 `props_keys` 就是不符，§3.2）。`structelem_keys` 必須等於驗證器在本機原檔上走 `/StructParents` → `/StructTreeRoot /ParentTree` → 該頁的 `/StructParents` 整數 → wrapper `MCID` 所得 StructElem 上 {ActualText, Alt, E, Lang} 的子集合（固定順序；四個都沒有、沒有 MCID、tree 沒有項目 → `[]`；該頁沒有 `/StructParents` → `null`；§3.2，H2）——寫 StructElem 的完整 key 集合（S、P、K、Pg…）就是不符。
- `mutation=null` 的紀錄：structure、growth_zone、render_mupdf、render_poppler、neighbours、glyph_identity、extraction、save_reopen 八個 phase 都是 `not_run`、detail="no mutation"，對應物件的可為 null 的欄位全 null（`text_state.after=null`、`neighbours.records_file` 指向一個只有 `role=untouched` 紀錄或空陣列的檔案）。**v3 null 形式（`brief_revision >= 3`，(f)）：`mutation == null` ⇔ neighbours 的十個 post-mutation 計數器 `glyphs_checked`、`unpaired_glyphs`、`target_glyphs_after`、`target_origin_delta_pt`、`untouched_max_origin_delta_pt`、`inshow_successor_max_origin_delta_pt`、`gid_mismatches`、`ink_mismatches`、`overlap_glyphs`、`halo_shadowed_glyphs` 全部為 null**——雙向：mutation 非 null 時七個計數必須非 null（`glyphs_checked`、`unpaired_glyphs`、`target_glyphs_after`、`gid_mismatches`、`ink_mismatches`、`overlap_glyphs`、`halo_shadowed_glyphs`），三個 origin 最大值（`target_origin_delta_pt`、`untouched_max_origin_delta_pt`、`inshow_successor_max_origin_delta_pt`）在空的 role 集合上照 `check_pairing` 的重算是 null，不得寫 0.0（寫 0.0 會被 `neighbours_summary_mismatch` 退件）；mutation 為 null 時任何一個非 null 都退件（violation `neighbours_null_form`；寫 0 是「我檢查過、沒有不符」的自撰宣稱，v2 的 schema 逼 CTRL_NEG 寫 0，兩次 pilot 都是這樣）；`glyphs_total`、`target_glyphs_before`、`pairing_rule`、`records_file` 仍必填非 null（before 側量得到）。同時 `mutation == null` 且 probe reason 落在 §3.0 的 unmapped 家族（含 detail 例外）的列，不論 kind，`target.replacement_provenance` 必須是 `unmappable`；寫了 `unmappable` 卻沒有家族 reason 也退件（§3.0 規則 1–3，violation `replacement_provenance_unmappable`）。

### 5.2 各 phase 的通過門檻（不得自訂或放寬；雜訊只能用 CTRL_DET 重算同一檔來處理）

驗證器對每個 phase 都用下面括號裡的欄位**重算**結果；你寫的 `result` 只是你的宣稱。Claude 端的 rederive 另外在本機語料庫原檔（以 `source.sha256` 解析，從不開你的 before.pdf）上**重新量測**同一組數字。

- **probe：**（重算自 `probe.*`）
  - max_tier=1 與 max_tier=0 都沒有例外；
  - handle 是新開的；
  - PREPARED 時 `binding_matches_target=true`；被拒時 reason 與 detail 已記錄。
- **structure：**（重算自 `mutation.*`、`text_state.*`）
  - **比較的對象與方式（v3 明文，(a)；live 與 reopened 共用）**：逐一走 `range(1, doc.xref_length())`，**排除**三樣東西：(1) 任何 `/Type /XRef` 的 cross-reference stream 物件（hvac 的 xref 9917 就是——MuPDF 在 prepare／commit 就重新產生 xref stream 的位元組與 trailer 的第二個 `/ID`，兩次 pilot 都因此把 9917 記進 `other_xrefs_changed_live`，structure 誤判 fail）、(2) trailer、(3) `/ID`。其餘物件：**stream 物件只比較 DECODED 位元組**（`doc.xref_stream(xref)`；acc `_object_entry` 的規則）——不比較 `xref_object(compressed=False)` 的文字、不比較 encoded bytes、不比較 stream dict 的 `/Length`／`/Filter` 序列化；**非 stream 物件（dict、array、純量）比較 semantic（解析後）相等**（acc `_objects_semantically_equal`：同一個解析值、只忽略 dict key 順序；任何 parse failure 視為不等）。pilot 的 run_pilot.py 以 `xref_object` 文字比 stream 物件、又沒排除 XRef stream，是契約沒說清楚，不是產品缺陷；
  - **live（commit 後、saveIncr 前）**：以上規則下每個非目標 xref 都相等（`other_xrefs_changed_live=[]`；對應 acc `_assert_only_target_streams_changed(semantic=False)` 的 stream 腿——dict 序列化文字不同但 semantic 相等的 xref 不進這個欄位，進 `other_xrefs_reserialized`）；
  - **reopened（saveIncr 後重開；排除 `/Type /XRef`、trailer、`/ID` 同上）**：套用產品測試的規則，原文照抄（acc:362-366 與 acc:335）：
    > ``semantic=False`` compares serialized object text exactly. ``semantic=True`` (save/reopen, plan §4) compares non-stream objects by parsed value ignoring only dictionary key order; streams always compare by decoded bytes.
    > `_objects_semantically_equal`: Same parsed PDF value up to dictionary key order; any parse failure is unequal.
    值不同的 xref 進 `other_xrefs_changed_semantic`（必須為空）；值相同但序列化文字不同的 xref 進 `other_xrefs_reserialized`（只記錄，不算失敗；/Rotate 頁的 /Page 物件預期會出現在這裡）；
  - 目標 stream 在宣告的 changes 範圍以外，位元組都相同（prefix `[0:start]` 與 suffix `[end_old:]`／`[end_new:]` 逐位元組相等）；
  - **恰好一個 changes 範圍**（splice_kind ≠ canary）；
  - **changes[] 對齊 token 邊界**（`token_aligned=true`）：start 與 end_old 必須是原 stream 經 `pdf_lexer.lex_content_stream` 重新 lex 後的 token 邊界（驗證器在本機語料庫原檔上自己重算）；
  - **新 operand 的 token 文法依 splice_kind 固定**（驗證器用 `model.text_commit.pdf_lexer.lex_content_stream` 重新 lex `new_operand_bytes_hex`，`new_operand_token_kinds` 只是你的附註）：

    | splice_kind | 新 operand 唯一允許的 token 序列 |
    |---|---|
    | `string_token`、`tj_item`、`string_fragment` | 恰好一個 string token（literal 或 hex） |
    | `whole_operator` | `[` string number `]` `TJ`（Tier 1 形狀） |
    | `tj_run` | string，後面可接恰好一個 number（K≠0 時）；沒有括號 |
    | `fragment_split`，`target.operator == "Tj"` | `[` 之後只有 string 與 number，number 至多一個，string 2 或 3 個，然後 `]` `TJ`（整個 operator 被換掉） |
    | `fragment_split`，`target.operator == "TJ"`（in-array） | string 2 或 3 個與至多一個 number，**沒有括號、沒有 `TJ`**（只換陣列裡那一個 string item token；陣列其餘 item 與每個 border kern 位元組不動，`border_kerns_byte_identical=true`） |
    | `canary` | 不限制；**只有 kind=canary 可以用**（驗證器交叉檢查 kind／path／method_id，§5.1） |

    出現任何其他 token（operator、name、inline image、dict……）→ 整案退件（這是「不得退回 legacy redact/reinsert」的機械檢查）；
  - **新 string token 綁定 replacement**：把文法允許的 string token 解碼（literal 去跳脫、hex 解碼）後串接，必須等於 `glyph_identity[]` 依 `index` 排序的 `code_bytes_hex` 串接（含 `is_space=true` 的空白碼），長度 = replacement 的 code unit 數（簡單字型 1 byte/字，Type0 2 bytes/字）。**`string_fragment`／`fragment_split` 只綁被替換的切片**（`byte_range_in_item=[b0,b1)`，解碼後位元組）：`string_fragment` 的新 token 解碼後 `[0:b0]` 必須與舊 operand 解碼後 `[0:b0]` 逐位元組相同、尾段與舊的 `[b1:]` 相同、中段等於 `glyph_identity[]` 串接；`fragment_split`（兩種形式相同）的第一個 string（b0 > 0 時）解碼後 = 舊的 `[0:b0]`、最後一個 string（b1 < len 時）= 舊的 `[b1:]`、中間的 string = `glyph_identity[]` 串接；in-array 形式另檢查 changes[] 範圍恰好是舊陣列裡的那一個 string token，`[`、`]`、其他 item、border kern 的位元組前後相同。非公開檔 `old_operand_bytes_hex` 為 null 時，prefix／suffix 比對由驗證器在本機原檔上做；沒有原檔則記 `unverifiable`（不是 pass）。neighbours 配對用的「字數差」由此**推導**（一般 = 新串接長度 − 舊 operand 長度；F3 = `len_new − (b1 − b0)`），不是你宣告的；
  - **show 數與 operator 數不變**：`show_count_after == show_count_before`（`replay_page_streams(...).shows` 長度）且 `operator_count_after == operator_count_before`（lex 後 operator token 數，逐 stream 加總；驗證器在本機語料庫原檔上重算 `operator_count_before`，rederive 重算 after）；
  - font xref 相同、font dict 的解析值相同（同上 semantic 規則）、FontFile 位元組的 sha256 相同；
  - 目標 show 與同頁每個非目標 show 的 text state 前後相等。比較的欄位：font_resource、font_size、tm、ctm、hscale、char_spacing、word_spacing、rise、render_mode、origin_user、**q_depth、extgstate_names、wrapper_stack**；
  - **wrapper bytes 不變**（`wrapper_bytes_unchanged=true`）的定義：對目標 show `mc_stack` 上的每一個 wrapper，其 BDC/BMC 的 operator＋operand token 位元組、以及配對的 EMC token 位元組，前後相同；位於 change 之後的 token，offset 只准平移 `end_new − end_old`；目標 show 的 `mc_stack`（tag、props、巢狀順序）相同。整個 span 當然含被改的 operand，所以**不是**要求整個 span 位元組相同；
  - 有 number token 時：驗證器用 `pdf_lexer` 從 `new_operand_bytes_hex` **重新解析**該 NUMBER token（`_NUMBER_RE`，`pdf_lexer.py:27`），\|parsed − K_written\| ≤ 1e-6；\|K_written − (K_sum + K_disp_engine)\| ≤ 1e-6，且 \|K_disp_engine − K_disp_hand\| ≤ 1e-6（`advance` 為陣列時逐一檢查）；`old_operand_bytes_hex` 存在時（公開檔）從舊 operand 的內部 NUMBER token 重算 `K_sum` 與 `internal_kerns_dropped`（非公開檔由 Claude 端在本機原檔上重算）。沒有 number token 而 `adv_new ≠ adv_old` → 退件（§5.1）。
- **growth_zone（第九個 phase；就是產品 `verify_tier1_commit` 在 `has_ink_growth` 時的三道 gate，一律唯讀呼叫產品函式）：**（重算自 `growth_zone.*`、`mutation.advance.*`、`target.*`、`source.page_rotation`）
  - `applicable`（§5.1 的同一條規則）：**`mutation=null`**（CTRL_NEG、CTRL_SYN_T1、negative、census）→ `applicable=false`、其餘欄位全 null、phase `not_run`、detail="no mutation"，適用性規則跳過（§5.3 規則 4 對 kind=control 且 mutation=null 不適用，直接走規則 7）；**`path=product_commit`** → `probe.commit.tier == 1` 且 `adv_new_text_space > adv_old_text_space`（鏡像產品 `PreparedEdit.has_ink_growth`，`plan.py:195-201`，與 `verify_tier1_commit` 只在 `has_ink_growth` 時跑 growth gate，`verify.py:1526`；`verify_bbox_page` 只由 `_build_tier1` 設定，`plan.py:2596`，所以 Tier 0 的 product commit 一律 false，即使 0 < Δ ≤ tolerance）；**`path ∈ {experiment, canary}`** → `displacement_ink > advance.advance_tolerance`（v3；`displacement_ink = Δ + K_sum·Tfs/1000`，§3.3 R7-1；`brief_revision 2` 的列用 Δ；tolerance 是產品對該 advance source 的容差，§5.1）；**與 kind 無關、與有沒有 K token 無關**（positive、control、canary 一體適用）。等寬（含 `|Δ| ≤ tolerance`）與縮短 → `applicable=false`，其餘欄位全 null；phase pass（detail="no ink growth"）**只在** `target.after_bbox_visual` 比 `target_bbox_visual` 在主增長邊多出 ≤ 0.5 pt 時（§5.1 交叉檢查；`_growth_zone_rect` 回 None 視為 0），否則 phase **fail**、detail 寫出主邊延伸量（pt）（reason `after_exceeds_target`；`brief_revision >= 3`；v2 是退件 `growth_after_exceeds_target`，§8 (n)）。依據：`target_bbox_visual` 與 `after_bbox_visual` 都是 PyMuPDF texttrace 的 **advance 框**（x1 = origin + advance，y 由字型的 ascender／descender），side bearing、斜體懸出、描邊外擴都不會讓它變寬，所以同字型、等 advance 的列不可能觸發（CTRL_POS_T0 的兩框位元組相等）；換字型則寬度與 y 範圍都會變（CANARY_FONT 在 hvac 上 +6.1 pt，§2.2，必記）。**product_commit 列（Tier 0，或 Tier 1 沒有 ink 增長）走到這個 fail 是產品發現，必列 PARENT_SUMMARY `product_findings`**（status 依 §5.3 規則 8）；`applicable=true` 時則是 **after 不得跑出 verify**：`_growth_zone_rect(target_bbox_visual, after_bbox_visual)` 的主邊延伸量 ≤ `_growth_zone_rect(target_bbox_visual, verify_bbox_visual)` 的主邊延伸量 + 0.5 pt（§5.1，H1；texttrace 字形框是 advance 框，誠實的列兩者相等到浮點雜訊，Basis (11)），否則 phase fail——被證明空白的區域必須涵蓋 after 的墨跡（v3 的 verify bbox 以 `displacement_ink` 建，§3.3 R7-1：`tj_run` 收進 K 的 tightening kern 讓 after 墨跡比 Δ 多出 K_sum·Tfs/1000，只用 Δ 的舊公式會把誠實的 F2G 列在這裡誤退）；
  - **verify bbox（視覺空間）**：product_commit 列 **照抄** `prepared.verify_bbox_page`（產品 `_grown_verify_bbox`，`plan.py:2366-2423`：沿 Tm×CTM baseline 向前加寬、橫向不變，經 `frame.inverse`／`frame.visual` 的 fitz float32 矩陣往返）；experiment／canary 列自己算：`target_bbox_visual` 在 `direction` 側延伸 `growth_pt`。驗證器兩種列都對公式重算，容差 **1e-3**（hvac p4 s26 實測產品值與公式差 2.4e-5；1e-6 會把必做的控制組退件）。`direction` 取 `after_bbox_visual` 相對 `target_bbox_visual` 延伸最多的那一邊（right/left/down/up，產品 `_growth_zone_rect` 的主邊規則）；
  - **strip（視覺空間；字形計數與 occupancy 用）**：`region_visual` = 產品 `verify._growth_zone_rect(target_bbox_visual, verify_bbox_visual)`（`verify.py:1130-1176`）：strip 介於 target 增長側邊緣與 verify bbox 同側邊緣之間，橫向 = 兩個 bbox 橫向範圍的聯集。strip 本身沒有 halo；halo 只出現在下面的 raster 區域族與 render 遮罩；
  - **strip（raw 空間）**：`region_dict` = `region_visual × ~frame.quarter_turn`（產品 `_growth_rect_in_dict_space` → `_visual_bbox_to_dict_space`，`verify.py:1191-1200,:247-268`）。texttrace、`get_drawings()`、`get_image_rects(xref)` 回傳的 rect 都在這個空間，相交一律用 `region_dict`；
  - **字形計數**：`before_glyph_bboxes_intersecting` = `verify.count_growth_zone_glyphs(meas_page, target_bbox=target_bbox_visual, verify_bbox=verify_bbox_visual)`（產品函式，`verify.py:1402-1416`；在**量測副本**上呼叫，before 狀態）。它只數**非空白** rawdict 字元（`_iter_nonspace_chars`，`verify.py:286-300`），目標自己的字元以 ±0.5 pt 邊界規則排除（`verify.py:1467-1488`）。所以目標後面緊接一個真正的空白字形**不算**佔用（Office 輸出、F3S／F2G 常見），而懸出自己 advance 的尾字（CMR10 `f`、斜體）也不會因 strip 從 target 邊緣起算而自傷——那是 raster 區域族的 guard 帶在處理。必須 = 0 才 pass；
  - `before_drawings_intersecting_bbox`：`page.get_drawings()` 中 `rect` 與 `region_dict` 相交者的個數（只記錄）。`before_drawings_not_provably_clear` = 0 才 pass：若相交的 drawing **全部**是純 stroke 直線段路徑，呼叫產品函式 `model.text_commit.stroke_occupancy.strokes_provably_clear(page, overlapping, region_visual, to_visual=frame.quarter_turn, margin=2.0)`（`stroke_occupancy.py:483`；`frame = model.text_commit.transforms.page_visual_frame_or_none(page)`；margin 是產品常數 `_STROKE_CLEARANCE_MARGIN_PT = 2.0`，`verify.py:65`）；回 True → 記 `stroke_proof="clear"`、`before_drawings_not_provably_clear=0`；回 False 或任何相交 drawing 不是純 stroke → `stroke_proof="failed"`、計入 `before_drawings_not_provably_clear`；**`frame` 為 None → `stroke_proof="failed"`**（產品 `_drawings_intersect_growth` 在 frame None 時回 True＝視為有墨跡，`verify.py:1224-1226`）；沒有相交 → `stroke_proof="not_needed"`。這一條就是 `_drawings_intersect_growth`（`verify.py:1203-1237`）；只准呼叫產品函式，不得自己重寫 stroke 幾何；
  - `before_images_intersecting` = 0：`for xref in page.get_images(full=True): page.get_image_rects(xref)` 的每個放置 rect 與 `region_dict` 相交者（`verify.py:1239-1257`；`get_image_rects` 的簽名是 `(name, transform=False)`，沒有 item 參數會拋例外）；
  - `sh_operator_present` = false（與產品 `_shading_presence`（`model/text_commit/verify.py`，內呼 `_page_has_shading_operator`）同規則，**頁級且 token-aware**，§14 (as)：先對這一頁**所有** content streams 各跑一次 regex `rb"(?<![A-Za-z])sh(?![A-Za-z])"`，**沒有任何一個 stream 命中 = false**（絕大多數頁到此為止）；有命中才把各 stream 以**一個空白**串成一個 buffer（MuPDF 讀 `/Contents` 的方式）做 content-stream lex，只有下列兩種情況算 true：（a）有 OPERATOR token 命中同一個 regex（`0sh` 這種黏在一起的字是一個 OPERATOR token，照樣命中），（b）有證明不了的內容（MALFORMED token、inline image 的 payload 或 `ID`、INERT_RUN），此時沿用 regex 的判決（= true）。命中落在**字串、註解或名稱** token 內（`(M sh M) Tj`、`% sh`、`/sh1 gs`）**不算**：它們不能執行 `sh`，產品也不再因此拒絕。v2–v8 寫的「任一處有 `sh`」比產品嚴；v9 起以本條為準。你的紀錄量到 true 就照實記 true（驗證器信任紀錄）；目前所有批次（十六個、479 筆紀錄）沒有任何一筆是 true）；
  - **raster 背景證明（產品的區域族，不是 strip）**：在量測副本上以 **96 dpi**（`verify._VERIFY_DPI`）取 `pix = meas_page.get_pixmap(dpi=96)`（這一頁若在同一個行程裡已經算過圖，呼叫前先 `fitz.TOOLS.store_shrink(100)`；而且這個 96 dpi 算圖本身就會污染 store，之後同頁的任何算圖都要先清，§5.2 render 的 store 規則 (e)），建 `pre_state = verify.PageState(streams=(), fonts=(), annots=(), nontarget_origins=(), pixmap_samples=bytes(pix.samples), pixmap_meta=(pix.width, pix.height, pix.stride, pix.n))`，然後：
    - `probe_regions_px_96dpi` = `verify.growth_probe_regions(target_bbox_visual, verify_bbox_visual, pix_meta)`（`verify.py:923-946`）= `(V∖guard(T)) ∪ (halo(V)∖halo(T))`，guard(T) = T 外擴 2 px（≈1.5 pt，`_GROWTH_EDGE_GUARD_PX`，`verify.py:870-873`），halo = 2 pt（`_HALO_MARGIN_PT`，`verify.py:59`）。所以增長 bbox 四周 2 pt 環內的任何墨跡（after 邊緣外 1 pt 的線、下一行的字形）都是 FAIL，即使它沒碰到 strip；
    - `background_bbox_visual`（**字型度量框，兩條路徑同一個輸入**）= `transforms.map_text_quad_to_visual(page, show.tm, show.ctm, (x_pre*Th, -0.35*Tfs, (x_pre + adv_old_text_space - K_inner/1000*Tfs)*Th, Tfs), frame=frame)`（沒有 kern 的整個 show 為目標時是產品 `_build_tier1` 算 `background_bbox_page` 的同一個 quad，`plan.py:2505-2516`；`Tfs` = Tf operand、`Th` = hscale/100、`adv_old_text_space` 是 §5.1 的 adv_old（切片目標時是切片的 advance）；1.35 em 高；`x_pre` = 切片之前所有 string item 的 advance（算法同 §5.1 的 adv_old），加上切片前每個 kern 數字 K 的 −K/1000·Tfs；F3 再加 item i0 裡 b0 之前位元組的 advance；整個 show 為目標時 `x_pre` = 第一個 string item 之前的 kern 總和的 −K/1000·Tfs（Tj 與無前置 kern 的 TJ 為 0）；`K_inner` = 切片內部、string item 之間的 kern 數字總和（切片之前的 kern 屬於 x_pre、切片之後的不算；單 item、F3、Tj 為 0；整個 show 為目標的 TJ 是所有 item 之間的 kern 總和）；沒有 kern 的整個 show（Tj）公式與產品 `_build_tier1` 相同）。product_commit 列照抄 `prepared.background_bbox_page`（同一函式同一輸入，位元相同）；experiment／canary 列自己呼叫這個產品函式。rederive 在本機原檔上重算（1e-3）；驗證器不自己重算，把它列為 unverifiable（`background_bbox`，見 (t)）。**不得**用 `target_bbox_visual`（1 em 的 texttrace 框）代替：`_target_background_rgb` 要求框內有嚴格多數色，1 em 框在小號拉丁文上沒有多數色——hvac p4 s26 實測：度量框 → 證明通過（2 個區域），texttrace 框 → "background: the target's own bbox has no majority background colour"，所以用錯框的實驗路徑每個增長案都會被自己的 growth_zone 擋掉；
    - `failure = verify._growth_probe_failure(pre_state, target_bbox=target_bbox_visual, verify_bbox=verify_bbox_visual, background_bbox=background_bbox_visual, page=meas_page, doc=meas_doc)`（`verify.py:1302-1367`）：產品自己依序跑 occupancy、`_target_background_rgb`（目標框內**嚴格多數**色；沒有多數色或目標墨跡不可見 → fail）、`_reference_confirms_background`（帶外參考點）、每個區域 `_region_is_uniform_pixels` 且 `_region_matches_reference_color`。`raster_proof` = "pass"（回 None）或 "fail"；`gate_detail` = 產品回傳的 `detail` 原文（ASCII）；`probe_regions_failed` = fail 時 1、否則 0；`background_rgb` = `_target_background_rgb` 的結果。**不得**另做 6x strip 像素計數當 gate（`render-growthstrip-before-6x.png` 只是給人看的附件）；
  - `growth_pt` = max(0, `displacement_ink`)·Th·`trm_scale`·`user_unit`（視覺 pt；v3：`displacement_ink = (adv_new − adv_old) + K_sum·Tfs/1000`，§3.3 R7-1——`splice_kind ∉ {tj_item, tj_run}` 與所有 product_commit 列的 `K_sum` 是 0.0，所以等於舊公式 max(0, adv_new − adv_old)；`brief_revision 2` 的列仍只用 Δ），其中 `trm_scale` = `math.hypot(linear[0], linear[1])`，`linear = transforms.combined_linear(show.tm, show.ctm)`（Tm×CTM baseline row 的 norm，產品 `_grown_verify_bbox` 的 `norm`，`plan.py:2384-2385`；**不是** `hypot(*linear)`——四分量的 Frobenius norm 在 hvac 上是 0.0849 而非 0.060；hvac p4 s26 實測 `growth_pt` = 43.959·0.799805·0.060·1.0 = 2.1095 pt，產品 `prepared.verify_bbox_page` 延伸 2.10956 pt，Basis (9)；寫入 `target.trm_scale`），`user_unit` = `frame.user_unit`（寫入 `target.user_unit`；產品 `_grown_verify_bbox` 在 user space 延伸 `growth_advance·norm` 再經 `frame.visual` 映射，`frame.visual` 帶 /UserUnit，`plan.py:2372-2379` 的 docstring 明說少了這個因子會把增長區算小）。hvac 與 fixture 的 user_unit 都是 1.0，/UserUnit 2 的頁會差一倍；`adv_new − adv_old` 不是自報數字：Claude 端的 rederive 用產品函式（`plan._advance`／`advance_points`，§0、M4）在本機原檔上重算 adv_old、adv_new、`advance_source` 與 `advance_tolerance`，差超過容差 → `quarantined: remeasure`，而且 rederive 餵給 growth gate 的 verify bbox 以**重算**的 Δ 建出，再與你的 `verify_bbox_visual` 比（1e-3）（H1）；
  - **遮罩面積**（驗證器）：`render.halo_area_pt2` = `(w_u + 6)·(h_u + 6)`，u = `target_bbox_visual ∪ after_bbox_visual`（1e-3），否則退件。
  這個 phase **就是** `verify_tier1_commit`（`verify.py:1493-1546`）在 `has_ink_growth` 時跑的三道檢查：`count_growth_zone_glyphs`（非空白字形）、`_occupancy_failure`（drawings＋stroke 證明、images、sh）、raster 背景證明（區域族含 2 pt halo 與 guard 帶）。每一道都由產品函式唯讀算出，而且**輸入也相同**：target bbox、verify bbox（公式或照抄）、字型度量框（同一個 `map_text_quad_to_visual` quad）、96 dpi pixmap、量測副本上的 page/doc——實驗路徑與產品路徑之間不再有任何輸入差異，所以結果與產品一致：該過的過（懸出 advance 的尾字、後面接空白字形、小號拉丁文旁的空白增長區），該擋的擋（halo 環裡的墨跡）；縮短不適用是因為產品的 `has_ink_growth` 也不跑它。三個 ORACLE twin（(ix)、(x)、(xi)）釘住這些方向。
- **render_mupdf：**（重算自 `render.mupdf.*`）
  - **store 規則（v3，(e)）**：同一個行程裡，任何一頁只要之前算過圖（任何 dpi／zoom——含 growth_zone 的 96 dpi pixmap、CTRL_DET 的重複算圖、6x crop、整頁 2x），再次 `get_pixmap` 之前**一律先** `fitz.TOOLS.store_shrink(100)`（清空 MuPDF 的 resource store）。Grok 在 pilot 實測：96 dpi 增長證明算圖之後，store 裡快取的降採樣影像讓同頁後來的 2x 整頁算圖差 24777 px，直到清空 store 才歸零——那是快取污染，不是編輯造成的差異，但驗證器不會替你分辨，`nontarget_changed_px` 就是 FAIL。每次清 store 都寫進 METHODS_AND_EVIDENCE_PLAN.md 的 `## Method`（`store_shrink_before_rerender: true`）與該案 `phases.render_mupdf.detail`；**不得**改用「複用同一個 pixmap」或「比較前先減掉已知差值」代替，也不得只在差值出現時才清；
  - 目標 crop zoom ≥ 6，`target_changed_px` ≥ 1；
  - 整頁 zoom 2 時，`nontarget_changed_px` = 0。遮罩 = `target_bbox_visual ∪ after_bbox_visual`（新舊目標字形 texttrace bbox 聯集，raw × `frame.quarter_turn`），再 ±3 pt（acc:855 的遮罩），`halo_area_pt2` 由驗證器從兩個 bbox 重算；
  - `control_rerender_changed_px` = 0；
  - live（commit 後未存）與 reopened 的整頁 samples 完全相同（`live_vs_reopened_changed_px` = 0）。
- **render_poppler：**（重算自 `render.poppler.*`）
  - 使用 `PDF_EDITOR_PDFTOPPM`，144 dpi；
  - before 與 after（已存檔）比較，門檻與 MuPDF 相同；
  - 沒有 Poppler → blocked（不是 pass，也不是 not_run）。v3／v4 下這個分支不該被走到：§1 step 0 在 `PDF_EDITOR_PDFTOPPM` 未設定時整批停在 `case_count: 0`；若跑 case 途中才發現它不可用（檔被移走、`-v` 失敗），該案記 blocked、README 說明，不得自己找或設定 pdftoppm。
- **neighbours：**（重算自 `neighbours.json` 每一筆）同頁**每一個**非目標字形（texttrace，量測副本）都要檢查：
  - **配對規則（`texttrace_order_origin_match/v1`）**：before／after 各把量測副本 `get_texttrace()` 的字形依 span 順序、字元順序攤平成一個 list（**含 Form XObject 與 annotation appearance 的字形**——texttrace 會回傳它們，replay 不會進 `Do`，它們一樣要配對、一樣要不動）。在 before list 裡用 origin 比對找到目標 show 的第一個字形（與 `fitz.Point(show.origin_user) * frame.base` 距離 < 0.02 pt（texttrace 在 `frame.base` 空間，不是 `page.transformation_matrix`，M1、H3），acc `_trace_for`（I0b 之後）同規則）得到整個 show run 第一個字形的索引 `s`，`i = s + c0`（v4：目標是切片時 `c0` = 目標之前的字形數，定義見 §4 M1「切片」；目標是整個 show 時 `c0 = 0`，`i = s`），目標 run = `[i, i+n_old)`；after 側的目標 run = `[i, i+n_new)`，`n_new − n_old` 是 structure 推導的字數差。其餘字形**依位置配對**：before 索引 `j < i` ↔ after `j`；`j ≥ i+n_old` ↔ after `j + (n_new − n_old)`。`show_index` 是該字形所屬 span 第一字 origin 比對到的 replay show（< 0.02 pt）；比不到任何 show（XObject／annotation 字形、hvac p1 那類 texttrace 多於 replay code unit 的頁）寫 −1，照樣配對、照樣檢查。`glyphs_total` = before 整頁字形數 − n_old；`len(after) − len(before)` 必須等於 `n_new − n_old`，否則 `unpaired_glyphs` = 差值的絕對值、neighbours FAIL；每個 before 字形恰好配對一次；禁止用「最近 origin」配對非目標字形；
  - `role=untouched`（未改動 show 內）：`origin_delta_pt` **= 0.0**（產品測試對非目標 show 的 origin_user 用完全相等，acc:858-864）；
  - `role=inshow_successor`（被編輯 show 內、編輯點之後；只有 F2/F3/F2K）：`origin_delta_pt` ≤ `(char_count_old + char_count_new)·Tfs·Th·trm_scale/1000 + 1e-6`（`brief_revision >= 4`；rev 2／3 仍是 1e-6）。MuPDF 把 simple font 的 `/Widths` 存成整數，texttrace 的字形前進是整數寬度（`20261025_1824_r2` 實測 `e` 走 444、`/Widths` 寫 444.4；`m` 833 對 833.3），K 卻用精確寬度算，每個字的前進差 `round(w) − w`（−0.5 到 +0.5 單位），所以替換後的後繼字差 Σ_new(round(w) − w) − Σ_old(round(w) − w) 個 /1000 單位（F3 `fragment_split` 兩列實測 0.00109 pt、0.00296 pt = 0.1×Tfs/1000、0.3×Tfs/1000）；等寬排列互相抵消，所以 P-B 量到 0.0。每個字實際最多差 0.5 單位，上限取每個字 1 單位的總和（留 2 倍餘裕）；真正的跳動（整個字寬以上）遠大於它；rederive 在 I0b 之後從 `/Widths` 重算精確殘差、1e-3 比對；
  - `role=target`：目標第一個字形 origin 差 **= 0.0**（acc:843），寫入 `target_origin_delta_pt`；**after 墨跡落地**：每個 `role=target`、`is_space=false` 的字形，在 after 的 6x crop（與 `render-mupdf-after-6x.png` 同一張）裡、其 `bbox_after`（raw × `frame.quarter_turn` 再乘 6）範圍內，與該 crop **嚴格多數色**不同的像素數寫入 `ink_after_px_6x`，必須 ≥ 1（crop 沒有嚴格多數色 → 記 fail，detail "no majority background in after crop"）；= 0 → neighbours FAIL。這一道抓的是被 `W n` clip path（或遮罩）切掉的替換字形：增長區 before 是空白（被 clip 的區域本來就空白）、after 的像素差 ≥ 1、texttrace 與 extraction 照樣回報字形，九個 phase 其他都會過；**產品的 verify 也沒有這一道**（`verify_tier1_commit` 與 V0 的 `verified_properties` 裡沒有「新字形有墨跡」的檢查），這是產品與 oracle 共同的盲點，由這一腿在 oracle 側補上（PART 3 風險 15；產品側是 N1 的 clip-extent 延伸）；
  - gid 相同；
  - **ink 檢查區** = 該字形自己的 bbox 扣掉「新舊目標字形 bbox 聯集 ±3 pt halo」（與 render 遮罩同一個 halo，不是新門檻）；區內 6x ink 差必須 = 0。bbox 落在 halo 內但不在未膨脹聯集內的字形：`ink_checked=false`、`halo_shadowed=true`，計入 `halo_shadowed_glyphs`（只記錄；它們的覆蓋由 growth_zone 的 raster 區域族 `halo(V)∖halo(T)` 與非空白字形計數負責，見 §5.2 growth_zone）；
  - bbox 與**未膨脹**的新目標字形 bbox 聯集（`target.after_bbox_raw`）相交、且 `is_space=false` 的字形：`overlap=true`、不做 ink 比較，計入 `overlap_glyphs`（`is_space=true` 的字形只記 `overlap=true`，不計數——疊到一個沒有墨跡的空白碼不是缺陷，與產品 `_iter_nonspace_chars` 同規則）。**kind ∈ {positive, control, canary} 時 `overlap_glyphs > 0` 是 FAIL**（代表替換字蓋到了鄰字）；kind=negative 只記錄；
  - `glyphs_checked` 必須等於 `glyphs_total`。
- **glyph_identity：**（重算自 `glyph_identity[]`）每個替換字（`is_space=false`）都要滿足 (a) 與 (c)；(b) 只在同一 font xref 的非目標位置有該字的出現處時才要求，沒有出現處時記 `consistency=null`、`gid_equals_consistency=null`，該字由 (a) 與 (c) 判定（變更 (m)）：
  - (a) gid ≠ 0 且有輪廓；
  - (b) 一致性檢查（`consistency`；**不是獨立證據**，簡單字型下它與 (c) 共用同一張表）：在同一 font xref 的非目標位置找一個該字的出現處，gid 必須相等。挑選依據：簡單字型依 glyph name 或 (3,1) 反查（`selected_by=glyph_name`/`cmap_31_reverse`/`standard_14_table`）；Type0 依嚴格 ToUnicode 的 CID→字（`selected_by=cid_tounicode`）。**不得依 texttrace 的 unicode 挑選**（它就是 ToUnicode）；找不到出現處（例：CTRL_SYN_T0 的替換字「再」「見」只出現在目標 show）→ `consistency=null`、`gid_equals_consistency=null`，(b) 不適用（不是 not_run，也不是 fail）；`consistency` 若是 null 以外的非物件值 → phase not_run（`consistency_malformed`）；
  - (c) 獨立腿（`independent_leg`）：
    - Type0：寫入的 CID 經嚴格解析的 ToUnicode 回到該字（產品本身以此准入，是已知的共同假設，記在 limits）；
    - 簡單字型（嵌入，有名稱）：寫入的 code 經字型程式自己的編碼得到 glyph 名稱，`fontTools.agl.toUnicode` 等於該字（`glyph_name_agl`）；
    - 簡單字型（嵌入 TrueType，`post` 無名稱）：code → gid（§9.6.6.4 cmap 路徑）→ 同一支字型 (3,1) cmap 反查 Unicode 等於該字（`cmap_31_reverse`）；
    - 簡單字型（未嵌入 Standard 14）：`standard_14_table`；
    - **ToUnicode 對簡單字型不是獨立腿**：ToUnicode 只能印證，不能獨立作證；
    - **`independent_leg.gid`**：獨立腿走到的 gid（code → 字型程式自己的編碼／cmap → gid；Type0 = CID → CIDToGIDMap）必須等於 `gid_after`（MuPDF 實際畫的 gid），每個 `is_space=false` 的替換字都要；不等 → phase fail（獨立腿替一個字作證，畫的卻是另一個 glyph）。
    - **`independent_leg.value`**：獨立腿推導出的那個字（Type0：ToUnicode 回到的字；`glyph_name_agl`：AGL 對應的 Unicode 字，不是 glyph 名稱；`cmap_31_reverse`／`standard_14_table`：反查得到的字）。`equals_char` 只是你的附註：`brief_revision >= 3` 的驗證器以 `value == char` 重算它（不同 → `glyph_note_mismatch`，phase 依重算值判 `leg_char_differs`），並把 `char` 綁到 `corpus_case.replacement[index]`（不等 → `glyph_identity_char`）；`consistency=null` 時 `gid_equals_consistency` 必須是 null（不是 → `glyph_note_mismatch`）。
  - 獨立腿無法取得（`none`）、`independent_leg` 缺少或不是物件、或腿種類與字型種類不符 → 此 phase 記 not_run（`no_independent_leg`），案例判 insufficient_evidence；`consistency=null` 不是 not_run 條件（見 (b)）。
- **extraction：**（重算自 `extraction.*`）
  - after 檔在目標 origin（±0.02 pt）取出的文字 = replacement；
  - 舊文字沒有殘留在目標位置；
  - 非目標 texttrace span 的文字變化數 = 0；
  - 注意：這個 phase 的字串來自 ToUnicode，所以它**不能**單獨證明字形正確；字形正確由 glyph_identity 的獨立腿證明。
- **save_reopen：**（重算自 `save_reopen.*`、`mutation.new_objects_*`）
  - saveIncr 後用全新 handle 重開，頁數相同；
  - 新增的物件號全部是 `/Type /XRef`（可以一個都沒有）；
  - live 與 reopened 算圖相同；
  - text_state、extraction、glyph_identity 在重開後都仍成立；
  - 來源 sha256 不變；
  - `mutation.saved_with == "saveIncr"`（這個 phase 定義在 saveIncr 上；`save_full` 的紀錄 save_reopen 記 fail，不是 not_run）。

### 5.3 status 判定表（機械判定；Claude 用同一張表重算，不一致就退件）
先做 §5.2 的逐 phase 重算；任何一個 phase 你寫 pass 而重算是 fail → 整案 VALIDATION reject（不是改 status）。然後依序：

1. **blocked：** 來源缺漏或 sha 不符；PyMuPDF 不是 1.27.x；`code_revision.tracked_diff_empty` 不是 true；或任一 probe 的 result=exception。例外屬於產品發現，要列入 product_findings。
2. **out_of_scope_vector：** 目標位置沒有任何 show，只有路徑或影像。必須附 get_drawings 或影像證據。
3. **kind=negative 或 census：**
   - probe 被拒，且（negative 時）reason == expected_reason（且該 expected_reason 在 §6.1 預註冊區塊裡），且副本 bytes 不變 → probe_rejected；
   - 否則 → insufficient_evidence。reason 不符時寫進 observation，那是新發現。
4. **insufficient_evidence（優先於 5、6、7）：** kind=positive，或 kind=control 且 `mutation ≠ null`（**CTRL_NEG 這類 kind=control、mutation=null 的紀錄不適用本規則，直接走規則 7**），且下列任一：九個 phase 任一為 not_run 或 blocked（growth_zone 不適用時的 pass 不算 not_run）；binding 不符；glyph_identity 沒有獨立腿；Poppler blocked；calibration=fail；`pre_registered=false`；`unpaired_glyphs>0`；驗證器重算與自報不一致。
5. **九個 phase 全 pass** → save_reopen_pass。
6. **前八個 phase pass，且 save_reopen.result == "fail"**（真的失敗，不是沒做）→ splice_pass。
7. **probe 被拒，且每個已做的實驗都至少有一個 phase=fail**（否定證據完整）→ probe_rejected。
8. **其餘情況** → insufficient_evidence。product_commit 列（Tier 0，或 Tier 1 沒有 ink 增長）因 growth_zone `after_exceeds_target` fail 落到這裡 → 產品發現，必列 PARENT_SUMMARY `product_findings`（§5.2 growth_zone）。

- control 與 canary 也照表計算 status，但校準判定看 §2。
- 類別層級的狀態只寫在 PARENT_SUMMARY，不得寫進 case status。可用值：`open`、`needs_second_case`、`needs_negative`、`method_reproducible`、`method_reproducible_single_family`、`by_design_refusal_candidate`、`insufficient_evidence`。**實驗路徑（path=experiment）的 save_reopen_pass／splice_pass 在 Claude 重新量測通過前只是假設**，PARENT_SUMMARY 的 `class_state_proposal` 一律是提案，由 rederive 的 remeasure 結果定案。
- **以上任何 status 都不是產品成功。**

### 5.4 遮蔽
- 專有檔與 local_unrecorded 檔（provenance ∉ {public, synthetic}）一律：
  - `corpus_case.original=null`、`target.source_decode.latin1=null`、`target.source_decode.independent=null`、每個 `changes[].old_operand_bytes_hex=null`（驗證器強制；對應的 `*_sha256` 欄位必填；Claude 在本機語料庫原檔上重算這些值）；`source.relative_path`：proprietary 與 synthetic 為 null（驗證器強制）；local_unrecorded 與 public 填路徑（`brief_revision >= 4` 驗證器強制，`relative_path_required`；遮蔽的是文字欄位，不是檔案身分）；
  - 客戶或機構字串（Producer、Creator、BDC props 中的人名等）改成 `[PLACEHOLDER_n]`，並記錄原字串 UTF-8 的 sha256。`[PLACEHOLDER_n]` 字面值（`^\[PLACEHOLDER_[0-9]+\]$`）在每一層掃描都是白名單，所以遮蔽後的 producer／creator 不會再被當成客戶字串。
- 公開檔的文字可以保留。
- replacement 永遠是明文，所以只能用非識別字串。
- **唯一例外（calibration-row exemption，只豁免第二層掃描）：** class_id ∈ {CTRL_POS_T0, CTRL_POS_T1, CTRL_NEG} 的 original 與 replacement 字串（共五個，已經以明文存在於 `test_scripts/test_text_commit_real_corpus_acceptance.py:71`、`:93-94`、`:486`）在**掃描欄位**（`extraction.after_text_at_target`、`glyph_identity[].char`、`corpus_case.replacement`）可以照寫；驗證器以**字串字面值**白名單放行這五個字串（`CALIBRATION_STRINGS`）、且只在這三個 class_id 與以 CTRL_POS_T0／T1 為基底的六個 canary class_id（CANARY_KSIGN、CANARY_TC、CANARY_FONT、CANARY_UNSAVED、CANARY_WRONGGLYPH、CANARY_INK；`CALIBRATION_CLASSES`）的紀錄裡（它們的 `extraction.after_text_at_target` 依設計就是原字串或替換字串，§2.1），其他地方出現仍退件。**它不豁免 null 規則**：這九個 class_id 的 `corpus_case.original` 仍必須 null（`redaction_null_required`，上一條），只有 `original_sha256` 帶該明文的 sha256。CANARY_GROWTH 不在豁免內（兩個站點都不帶校準字串）。
- **`redaction.scan` 不是自我宣告**：你寫你的掃描結果；驗證器用自己的掃描重算，驗證器 `client_strings_left` 或 `machine_paths_left` > 0 就退件，不管你寫什麼。掃描分三層：
  - **全部欄位**（含批次層 MD）：device-guard PATTERNS（`scripts/hooks/pre_commit_device_guard.py:46-61`）與本機 denylist（`test_files/.redaction_denylist.txt`；拉丁條目逐字、大小寫不分、整字比對，CJK 條目子字串比對；**檔案不存在且批次有任何非公開的 `brief_revision >= 3` 列 → 批次層 `denylist_missing`，rederive 視為 blocking、整批拒收；這是 owner 前置條件（§1），你不得建立它，只能寫進 README `## Pilot limits`**）；
  - **資料欄位**（非公開檔 case 才掃）：`source.producer/creator`、`text_state.*.wrapper_stack[].props_keys/structelem_keys`（白名單比對；`structelem_keys` 只會是 {ActualText, Alt, E, Lang} 的子集合，四個都在白名單裡——它不是 StructElem 的完整 key 集合，H2；`props_keys` 只會是 inline dict 的頂層 key，name operand 時是 `[]`，所以 hvac 的 `/OC /MC0 BDC` 掃不出任何東西）、`text_state.*.wrapper_stack[].props_name` 與 **`wrapper_stack[].tag`（v3，R7-2 (j)）**（/Properties 資源名例如 `MC0`，以及 BDC/BMC 的 tag 例如 `Span`、`TOCI`、`THead`、producer 自訂再 role-map 的 tag：**tag 用的是 PDF name 字元集**：`tag` 必須 fullmatch `[A-Za-z0-9_.-]{1,127}`（驗證器 `_is_ascii_name`；空字串、空白、`#`、`(`、128 字以上都不過），不符記 violation `client_string`、計入 `client_strings_left`；**`props_name` 用的是可印 ASCII 規則**——每個字元在 0x20–0x7E 即過，不符記 `props_name_not_ascii`、同樣計入 `client_strings_left`。兩者都不做白名單逐字比對。v2 對 tag 用的 Table-333 白名單漏掉 BlockQuote、Caption、TOC、TOCI、THead、TBody、TFoot、Ruby、Warichu、RB/RT/RP/WT/WP 與所有 role-mapped 的 producer tag，會把誠實的專有 F1 列退件；v3 起 tag 不再對 Table 333 比對，非 ASCII 的 tag 計入 `client_strings_left`，ASCII 的客戶字串由第一層 denylist 抓）、`extraction.after_text_at_target`、`glyph_identity[].char`、`target.source_decode.latin1/independent`、`corpus_case.original`、`changes[].new_operand_bytes_hex`（`old_operand_bytes_hex` 在非公開 case 必為 null）。**hex 欄位只掃 string payload，不掃 token 文字**：驗證器先用 `pdf_lexer.lex_content_stream` 重新 lex `new_operand_bytes_hex`，只取 STRING／HEXSTRING token 的 payload（literal 經 `decode_literal_string` 去跳脫、hex 經 `decode_hex_string` 解碼）；數字、括號、operator、hex 數字本身永遠不當文字掃（把 `<0027…> Tj` 或 `[<…> 333.000000] TJ` 的 token 文字以 UTF-16BE／latin-1 解碼會憑空產生 CJK 碼位與字母碎片——hvac p4 s11／s26 實測各 18／13 個 CJK 碼位——那正是 C-5 第二次沒修好的原因）。`font_kind=simple`：payload 以 latin-1 解碼後掃（**不做 UTF-16BE**：1 byte/碼，拉丁 payload 以 UTF-16BE 解碼必然落在 CJK 區，例如 "He" = U+4865）；`font_kind=type0`：payload 是 2-byte CID，**不當文字解碼**，每個 CID 必須出現在 `glyph_identity[].code_bytes_hex`，或（F3 的 prefix／suffix、canary 的 donor 字）同一 show 舊 operand 的 CID 集合（本機原檔；沒有原檔 → `unverifiable`，不是 pass），否則計入 `client_strings_left`；字元本身經 `glyph_identity[].char` 掃。白名單 = {該案 `replacement`、`RejectReason` 全部值、wrapper class slug 全部值、ISO 32000-1 標準結構類型名（Table 333：Document、Part、Art、Sect、Div、P、H、H1–H6、L、LI、Lbl、LBody、Table、TR、TH、TD、Span、Quote、Note、Reference、BibEntry、Code、Link、Annot、Figure、Formula、Form、Artifact、OC——v3 起這張表**不再**用在 `wrapper_stack[].tag`，tag 改走 ASCII 規則，R7-2；它只留給 `class_slug` 等其他白名單欄位）與標準 property key（MCID、Lang、E、ActualText、Alt、Type、Subtype、BBox、Attached、O、OC；OCG 字典的 key 永遠不併入 `props_keys`——若未來 schema 加入 OCG 解析欄位，它有自己的欄位與自己的白名單：Type、Name、Usage、Intent、OCGs、P、VE，本輪沒有這個欄位）、schema enum 詞彙、brief 欄位名、`[PLACEHOLDER_n]` 字面值、五個校準字串（只在三個 CTRL class_id）}；**斷詞規則（機械）：** 拉丁字 = 以 `re.findall(r"[A-Za-z]+", text)` 切出的每一段 ASCII 字母連續串，比對前兩邊都 `casefold()`（任何長度，連單一字母也算一個字）；CJK 字 = 每個 `unicodedata.name()` 以 `CJK UNIFIED IDEOGRAPH`、`CJK COMPATIBILITY IDEOGRAPH`、`HIRAGANA`、`KATAKANA` 或 `HANGUL SYLLABLE` 開頭的 code point，逐字比對（白名單字串的每個字都算在白名單裡）。**數字、標點、括號、空白與其他符號永遠不成詞、不被掃**（所以「空調冰水管線系統圖(1)」只產生九個 CJK 字，`(1)` 不是字串，CANARY_UNSAVED／CANARY_WRONGGLYPH 抽出原字串也不會被第二層退件），其他文字系統的字母（重音拉丁、希臘、西里爾）只受第一層 denylist 約束（風險 8 記為殘餘）。這些欄位裡每個 CJK 字與每個拉丁字不在白名單 → 計入 `client_strings_left`；
  - **產品 detail 欄位**（`probe.max_tier_1.detail`、`probe.max_tier_0.detail`、`growth_zone.gate_detail`）：是產品的英文模板（`model/text_commit` 的 detail 字串只插入計數、浮點數、operator／render_mode／slug、font resource 與 basefont 名稱），**改列第一層，再加 ASCII 規則**：每個字元必須在 0x20–0x7E，任何非 ASCII 字元計入 `client_strings_left`；不做白名單逐字比對，所以 CTRL_NEG 的 "no CID maps to a replacement character"（`cid_fonts.py:959-962`）、F1 的 "wrapper class: <slug>"（`marked_content.py:420-421`）、S10 的 "3 of 3 listed /Annots entries are inline dictionaries (no xref)" 照寫即過；
  - **自由文字欄位**（§1 語言規則列出的那些）：只做第一層；**不做長度或 CJK 啟發式**。非公開 case 的自由文字出現 CJK → `language_warnings` +1（不退件，Claude 端 triage 逐條看）。
  公開檔與 synthetic 的 case 只做第一層。
- `neighbours.json` 不得含文字欄位（§5.1）。

## 6. 批次層必交檔案（`_evidence_pilot/<YYYYMMDD_HHMM>_r2/`）
1. **`METHODS_AND_EVIDENCE_PLAN.md`**
   - 在第一次修改任何副本**之前**寫好。內容：預定案例清單（class、來源、show、variant、method、每案最多 3 個假設、唯一變因）。
   - **必須含一個 fenced ```json 區塊**，結構固定：
     ```json
     {"pre_registration": "true-text-plan/2",
      "cases": [{"class_id": "F30B", "slug": "multicolumn", "page_index": 0, "show_seq": 3,
                 "variant": "eq", "method_id": "M2_COMMIT", "expected_reason": null,
                 "hypotheses": ["H1 ...", "H2 ..."]}]}
     ```
     驗證器解析它：任何 case_record 的 (class_id, slug, page_index, show_seq, variant) 不在清單中，或 `expected_reason` 與清單不同 → 該案 `pre_registered=false` → insufficient_evidence。計畫寫好後才發現的 show 本輪只能記 census。**計畫列本身不合 plan schema（例如 slug 不合 pattern、variant 不在詞彙內）時，後果也是逐案的（§8 (o)）**：該列照樣登錄（引用它的 case 不會因此變成 `pre_registered=false`；只有 key 欄位不是純量——list／object——的列登錄不了任何 case，引用它的 case 走 `pre_registered_mismatch`）；驗證器把這條 violation（file 仍是 `METHODS_AND_EVIDENCE_PLAN.md`、pointer `/cases/<i>/…`、code 不變）記到每一個 (class_id, slug, page_index, show_seq, variant) 與該列相同的 case 上，那些 case 整案退件（rederive 記 `validator_rejected`），批次其餘的 case 照常 rederive；沒有任何 case 引用的前沿壞列只記 unverifiable `plan_row_invalid`，不影響任何 case（rederive 不會關閉它，留在 `unverifiable_closure.open`）。R0 校準列（class_id 為 CTRL_* 或 CANARY_*，或被 kind=control／canary 的 case 引用）的計畫列 violation 仍是批次層，rederive 整批拒收——R0 是批次層前提（§2.3），不逐案化；class_id 讀不出前沿類別的列（不是物件、class_id 不在詞彙內）同樣留在批次層。`/cases/<i>` 以外的計畫層問題（缺 fenced 區塊 `plan_block_missing`、`pre_registration` 值或頂層形狀不合 schema、`methods_plan_sha_mismatch`）仍是批次層，rederive 整批拒收。
   - 它的 sha256 寫進每一案的 `methods_plan_sha256` 與 PARENT_SUMMARY。
   - `run_pilot.py` 必須接受 `--plan-sha`；計畫檔不存在或 sha 不符時，拒絕做任何 mutation。
   - **`## Helpers` 一節（v3 (g)）**：列出 `<batch>/helpers/` 裡每一個檔名（沒有就寫 `none`）與一行用途（英文 ASCII）。驗證器**不**比對這份清單（沒有 helpers 規則；它對 `helpers/*.py` 只做 §5.4 redaction 掃描）；Claude 端 triage 人工對照目錄與清單，多一個或少一個檔都退件。
   - **`## Method` 一節**含 `store_shrink_before_rerender: true`（(e)，§5.2 render）與 `displacement_ink = (adv_new - adv_old) + K_sum*Tfs/1000` 的公式（(i)，§3.3），讓方法本身可被對照。
2. **`run_pilot.py`**
   - 重跑方式：`.venv\Scripts\python.exe -B _evidence_pilot\<stamp>\run_pilot.py --plan-sha <sha> --phase code_revision|r0|cases|all`（v5：`code_revision` 是第一個 phase，見 §1 (x2)）。
   - **單一 runner（v5 (w)）**：同一批次的所有 case 列與 calibration 必須來自同一份 `run_pilot.py` 文字。對 `run_pilot.py` 或任何會寫 `cases/`、`cases.json`、`PARENT_SUMMARY.json` 的 helper 的修改只允許發生在第 8 項的 self-check 迴圈內，修改之後必須在同一個戳記內重跑**整批** `--phase all`（算一次 R0 attempt，上限 3）；在較早的 `--phase all` 之上補跑 `--phase cases`／`--phase r0` 的混合形狀為退件。不寫上述三者的 bookkeeping helper（plan、README、limits、DONE、code_revision 的寫入器）不受此限，只需列進 `## Helpers`。因其他理由（例如重新解讀 summary 規則）改 runner 一律開新戳記。機制：`run_pilot.py` 在每次 `--phase` 開始時把 `{phase, runner_sha256, started_utc}` 追加到 `<batch>/RUNS.json`（每一項都必須是格式正確的 `{phase, runner_sha256 (64 hex), started_utc}`，否則 `runs_malformed`；規則只檢查**最後一項**，較早的項目是嘗試歷史）；每列 case_record 與 PARENT_SUMMARY 的 `code_revision.runner_sha256` 記產生它的 run_pilot.py 的 sha256（rev ≥ 5 的 schema 欄位，選填鍵、rev ≥ 5 必填）。驗證器（rev ≥ 5）：`runner_sha_missing`（列或 PARENT_SUMMARY 缺這個欄位）、`runner_sha_mixed`（列之間或 PARENT_SUMMARY 與列不同）、`runner_sha_disk_mismatch`（記錄值 ≠ sha256(`<batch>/run_pilot.py`)）、`runs_missing`／`runs_malformed`（RUNS.json 缺或格式錯）、`runner_partial_rerun`（RUNS.json **最後一項**的 phase 不是 `all`，或它的 runner_sha256 ≠ 記錄值）；記錄值 = PARENT_SUMMARY 的 `code_revision.runner_sha256`（缺時取第一列的值）；六個 code 都是批次層，rederive 整批拒收。RUNS.json 與 code_revision.json 是 v5 新增的批次層檔案（不在 `file_missing` 規則內：缺 RUNS.json 是 `runs_missing`）；`--phase code_revision` 不需要 `--plan-sha`（計畫檔那時還不存在）。rev 4 以前的列或 PARENT_SUMMARY 帶 `runner_sha256` 是 `schema_additional`。`20261026_0032_r2` 的 R0 列來自 `--phase all`、前沿列來自改過 summary 邏輯後的 `--phase cases`（那個改動本身是對的，見 §3.0／(w2)），v4 無此規則，該批接受。
   - 自行把 repo 根目錄加進 sys.path；只以唯讀方式 import 產品模組（含 `stroke_occupancy.strokes_provably_clear`、`transforms.page_visual_frame_or_none`、`verify._growth_zone_rect`、`verify.growth_probe_regions`、`verify._growth_probe_failure`、`verify.count_growth_zone_glyphs`、`verify.PageState`、`verify._VERIFY_DPI`、`patch.kern_for_displacement`、`transforms.map_text_quad_to_visual`（字型度量框）、`transforms.combined_linear`（`trm_scale` = `math.hypot(linear[0], linear[1])`，baseline row 的 norm）、`plan._advance`／`FontCapability.string_width`／`IdentityHCidCapability.advance_points` 與 `DocumentFontRegistry`（`advance` 物件，H1）、`pdf_lexer.lex_content_stream`／`splice_stream`），不得 monkeypatch；不連網；只寫入自己的批次目錄。
3. **`cases/<case_id>/case_record.json` 與 `cases.json`**（內容一致）。
4. **`PARENT_SUMMARY.json`**，由程式從 cases.json 計算，不得手打。欄位：
   - `schema`: "true-text-parent/2"、stamp、brief_revision、code_revision、tool_versions、methods_plan_sha256；`brief_revision` 必須等於每一列 case 的 `brief_revision`（同一批次只有一種 brief 版本；不一致的列 `brief_revision_mismatch` 退件，否則一列寫 2 就能跳過所有 v3／v4 規則）；
   - `calibration`: {status: pass|fail|synthetic_only, attempts, controls{id: {expected, observed, ok}}（含 `CTRL_POS_T1.growth_zone.applicable=true` 與 `before_*=0` 的正向增長控制；`CTRL_SYN_T0` 的 Tier 0 九 phase pass；`CTRL_SYN_T1` 的 `max_tier_1=rejected/growth_region_not_blank`、detail 前綴 `glyphs:`、`commit.attempted=false`、`mutation=null`、growth_zone `not_run`、status probe_rejected）, canaries{id: {site, must_fail_phases, failed_phases, caught, legs{geometry_overlap, growth_zone_glyph, growth_zone_raster, neighbours_overlap}, missed_legs[]}}, growth_canary_sites[{site, page_rotation, show_seq}]}；
   - cases_total、by_status（六個 key 全列）；
   - `per_class{class_id: {cases, positives, negatives, distinct_lineages, distinct_producer_families, tier0_positive_pass, tier1_positive_pass, by_status{6}, class_state_proposal, remeasure_pending: true}}`（只計 kind ∈ {positive, negative, census}；control／canary 列只出現在 `calibration`）。**v5 (w2)**：`distinct_lineages`、`distinct_producer_families` 與 `class_state_proposal` 的判定只數 **status=save_reopen_pass 的 positive** 的 lineage 與 producer 家族（negative、census 不算；§3.0 的門檻本來就是「正例來自 2 個以上 lineage」）。驗證器對 rev ≥ 5 的批次（整批一個旗標）以同一定義重算 `distinct_lineages` 與 `distinct_producer_families` 並逐欄比對；`class_state_proposal` 不比對，只檢查不得高於重算結果（`class_state_overclaim`）；rev 4 以前維持全列計數；
   - `product_findings[{case_id, kind: engine_exception|false_safe_suspect|unexpected_prepare|unexpected_reason, detail}]`；
   - `counts_derived_from: "cases.json"`、`product_source_changes: 0`、`pytest_runs: 0`、`originals_untouched: true`。
   - 不變量：cases_total == len(cases.json)；Σby_status == cases_total；每類 Σby_status == cases；Σper_class.cases + （kind=control 與 kind=canary 的案數） == cases_total。
5. **每案資料夾：** case_record.json、neighbours.json、text_state.json、mutation.json、§1 規定名稱的 render-*.png。PDF 只放在 `candidates/`。
6. **`CROSS_BATCH_DELTA.json`**：只放在本批目錄內。不得修改 `20260924_2005_cross_batch`，也不得修改 `_evidence_pilot/CROSS_BATCH/`。
7. **`REDACTION.json`**（批次層的 placeholder → sha256 總表）、**`INVENTORY.md`**、**`README.md`**（只陳述數字與 status，不得有成功宣稱）。
8. **`VALIDATION.self.json`**（自我驗證迴圈；v3 (h)）：
   - 執行 `.venv\Scripts\python.exe -B scripts\evidence_bundle.py validate _evidence_pilot\<stamp>_r2 --out _evidence_pilot\<stamp>_r2\VALIDATION.self.json --self-check`。`--self-check` **只**跳過兩條 presence 規則——`DONE.json` 的 `file_missing`／`done_missing`，與 `VALIDATION.self.json` 自己的 `file_missing`——並在輸出寫 `"self_check": true`；其他每一條規則、每個 phase 重算、每層 redaction 掃描照常。沒有 `scripts/evidence_bundle.py` 就寫 `{"validator": "absent"}`。
   - 迴圈：逐條看 `violations`，只修**你自己的** bundle、`run_pilot.py` 或 `helpers/`；不放寬任何門檻，不改 `scripts/`、schema、產品碼；最多 3 輪；最後一輪的 `VALIDATION.self.json` 原樣保留，不得手改。**v3 新增、你會在 VALIDATION.self.json 看到的 code**：`violations` 裡的 `neighbours_null_form`（§5.1 null 形式）、`replacement_provenance_unmappable`（§3.0）、`displacement_ink_missing`／`displacement_ink_mismatch`（§5.1 R7-1）、`brief_revision_mismatch`（PARENT_SUMMARY 與列不一致）、`redaction_null_required`（hvac 列的 `original` 等欄位不是 null）、`client_string`／`props_name_not_ascii`（§5.4 tag／props_name）、批次層 `denylist_missing`（owner 前置條件，§1，**你修不了**：留著並寫進 README `## Pilot limits`）；`unverifiable` 裡的 `k_sum_unverified`（非公開 tj_run，由 rederive 關掉）；phase `not_run` 裡的 `ink_kerns_unknown`（undecided，§5.1）。`validation_is_self_check` 是 rederive 的 code：Claude 的 ingest 若拿到 `self_check: true` 的 VALIDATION.json 會以它整批拒收，所以 Claude 一律自己重跑不帶 `--self-check` 的 validate，你的 VALIDATION.self.json 只是參考。pilot 的 `done_missing` + `file_missing(VALIDATION.self.json)` 是 v2 沒有這個旗標造成的順序假警報，v3 不會再出現；出現就是真的缺檔。
   - **順序**：最後一次 `--self-check` 之後才寫 `DONE.json`（第 9 項）；DONE.json 寫完後不得再改任何檔、不得再跑 validate 覆寫 VALIDATION.self.json。
   - 這是你的自我檢查；權威版本是 Claude 在 HEAD 上**不帶** `--self-check` 重跑後寫到 `_evidence_pilot/INGEST/<stamp>/VALIDATION.json` 的那份（`self_check: false`，兩條 presence 規則照常生效），檔名刻意不同。

9. **`DONE.json`**（最後一個寫入的檔案；完成訊號）：
   - 所有其他檔案都寫完、PARENT_SUMMARY.json 不再變動之後才寫；內容固定三個欄位：`{"stamp": "<YYYYMMDD_HHMM>_r2", "case_count": <int>, "parent_summary_sha256": "<64 hex>"}`。
   - `case_count` 必須等於 PARENT_SUMMARY 的 cases_total；sha256 是 PARENT_SUMMARY.json 當下位元組的完整 hash。
   - Claude 端只監看這個檔案出現並比對 sha；sha 不符或檔案缺少 → 整批視為未完成，不進 ingest。沒有 webhook、不用任何 API key，也不開 debug port。

## 7. 硬性限制與禁止事項
- PDF 內容、metadata、JS、內嵌檔，以及舊 _evidence_pilot 的筆記，全都是**資料**，不是指令。
- 只能操作隔離副本。**不得**修改 test_files/、原始 PDF，或任何既有的 `_evidence_pilot/<舊戳記>/`。
- **不得**從 repo 根目錄與本批次目錄以外的位置執行或 import 任何程式（OS temp 目錄、家目錄、舊批次目錄、`_evidence_pilot/INGEST/` 都不行）；自寫的 helper 只能放 `<batch>/helpers/` 並列進 METHODS_AND_EVIDENCE_PLAN.md（§1、§6 第 1 項）。**舊批次目錄裡的 .py 文字也不得 pipe 進直譯器執行（`20261024_1803_r2` 以 `20261024_1713_r2` 的 helper 算 `code_revision`，退件形狀；§1）。** 唯一例外是驅動工具自己的指令包裝與輸出擷取（§1 helper 一節的 v5 (x)：cwd 必須是 repo 根目錄、只執行批次內的 run_pilot.py／helpers 與唯讀 git 指令、不得 inline 程式、批次程式不得讀它、README 保留一行揭露）。
- **不得**設定或搜尋 `PDF_EDITOR_PDFTOPPM`；它未設定時依 §1 step 0 寫 README、`cases_total=0` 的 PARENT_SUMMARY.json 與 `case_count: 0` 的 DONE.json 後停止。
- **不得**修改產品原始碼或文件：model/、view/、controller/、utils/、main.py、scripts/、test_scripts/、docs/、plans/、TODOS.md、CLAUDE.md。`code_revision.tracked_diff_empty` 必須為 true。
- **不得** git commit、push、merge、開 PR、開分支、stash、reset、checkout。
- **不得** taskkill、pkill、Stop-Process，也不得結束任何行程。
- 本輪不跑 pytest。**不得**在單一行程跑 `pytest test_scripts/`。
- 不上雲、不外傳 PDF、不連網下載，也不用外部或 GUI 編輯器存檔。
- **不得**換字型、縮小字形、擴充 subset、自創間距門檻或像素容差，也不得退回 legacy redact/reinsert（§5.2 structure 的 token 文法與單一 change 範圍會抓）。
- **不得**以信心、截圖或「打得開」宣稱成功。structure、影像、growth_zone、save-reopen 任一項無法完成 → insufficient_evidence。
- **不得**自編 case_id、hash 或 PDF；hash 一律重算完整 64 位 hex。
- 任何輸出檔都不得含絕對路徑、使用者名稱或主機名。直譯器只寫成 `.venv\Scripts\python.exe -B`。

## 8. v3 變更紀錄
每一條都來自 2026-10-24 兩次 pilot（`20261024_0702_r2`、`20261024_1114_r2`）與 full 批次 `20261024_1803_r2`、`20261024_2116_r2` 的 triage 或 round-7 refuter 的殘餘項；除 (m)、(n) 與 (o) 外全部 fail-closed，沒有放寬既有門檻。(n) 不改任何門檻：0.5 pt 與三條 after-bbox 幾何檢查的到達條件不變，只把後果從整案退件（bundle violation）改成 growth_zone phase fail，而且只對 `brief_revision == 3` 生效（語意變更；brief-v2.md 第 604／650 行是舊文字，原樣保留，1114 批次照舊驗證）。(m) 是本節兩條放寬中的第一條（第二條是 (o)，見本段末）：它把 §5.2 glyph_identity 導語對每個替換字都要求的 (b) 收窄到「同一 font xref 有該字的非目標出現處」的情況，化解 §5.2 導語／(b) 與 §2.1（固定的 CTRL_SYN_T0 fixture 與替換字，九 phase 全 pass）之間的內部衝突，依 (c) 的 not_run 條件與 extraction 注意（字形正確由獨立腿證明）判定；因 brief-v2 含同一衝突，(m) 不分 `brief_revision`。(m) 隨附的三條收緊（重算 `equals_char`、`char` 綁定 `replacement[index]`、`consistency=null` 時附註必須 null）與其他 v3-only 規則一樣只對 `brief_revision == 3` 生效。契約決定：schema 檔名仍是 `*.v2.schema.json`、`schema_version`／contract 仍是 `true-text-case/2`；`brief_revision` const 2 → enum [2, 3]；每一條 v3-only 規則都只對 `brief_revision == 3` 的紀錄生效，`brief_revision 2` 的 1114 批次照舊驗證與 rederive。(o) 是第二條放寬，同樣不分 `brief_revision`：它只把前沿計畫列的 plan-schema violation 從批次層改歸到引用該列的 case（R0 列仍是批次層）；brief-v2.md 第 750 行與本版 §6 第 1 項是同一句逐案的預註冊規則，沒有任何一版說過壞的計畫列會讓整批拒收；沒有計畫列 violation 的批次驗證與 rederive 結果不變。

| id | 變更 | 觸及章節 |
|---|---|---|
| (a) | structure phase 明文排除 `/Type /XRef` cross-reference stream、trailer 與 `/ID`；stream 物件只比 DECODED 位元組（acc `_object_entry`），非 stream 物件比 semantic（解析後）相等——pilot 兩次把 xref 9917 記成 `other_xrefs_changed_live` 是契約沒說清楚 | §5.2 structure（live／reopened） |
| (b) | 「adv 必須等於 `prepared.source_advance`／`replacement_advance`」只對 Tier 1 成立；Tier 0 的 `PreparedEdit` 留 0.0（`plan.py:165-166`），`advance.adv_*` 用 `advance_points`／`plan._advance` 實測，`prepared.*` 照抄 0.0 | §2.1 CTRL_POS_T0、§4 M1 步驟 4、§4 M2、§5.1 advance 來源規則 |
| (c) | hvac／ecc 的 provenance 是 `proprietary`（acceptance `CORPORA` + manifest `corpora` 以 sha 登錄），不是 `local_unrecorded`（兩次 pilot 因此 `quarantined: provenance_unverified`）；五個校準字串只對 §5.4 **第二層掃描**豁免（`CALIBRATION_STRINGS` × `CALIBRATION_CLASSES`），「非公開 `corpus_case.original` 必須 null」（`redaction_null_required`）**沒有**例外，hvac 列的 `original` 一律 null；驗證器**沒有** provenance 規則，寫錯 provenance 由 rederive `quarantined: provenance_unverified` 抓 | §2.1 CTRL_POS_T0 來源欄與豁免段、§3.0、§5.1 null-original 規則、§5.4 |
| (d) | step 0 Poppler gate：`PDF_EDITOR_PDFTOPPM` 未設定 → README `blocked: PDF_EDITOR_PDFTOPPM unset` + `cases_total=0` 的 PARENT_SUMMARY.json + `case_count: 0` 的 DONE.json，在任何 case 之前停止；Grok 不得自己設定它，owner 在貼上前 export | §0.0、§1 step 0、§5.2 render_poppler、§7 |
| (e) | MuPDF image store 快取污染（96 dpi 增長算圖後同頁 2x 差 24777 px）：同一行程裡同一頁再次算圖前一律 `fitz.TOOLS.store_shrink(100)`，寫進 `## Method` 與 phase detail | §2.1 CTRL_DET、§5.2 growth_zone raster、§5.2 render_mupdf、§6 第 1 項 |
| (f) | `mutation == null` 的 null 形式：neighbours 十個 post-mutation 計數器可為 null 且**必須**為 null；反向：mutation 非 null 時七個計數必須非 null，三個 origin 最大值在空 role 集合上依重算為 null；`glyphs_total`、`target_glyphs_before`、`pairing_rule`、`records_file` 仍非 null；`replacement_provenance` 新 enum 值 `unmappable`（CTRL_NEG 依構造；只限 negative／control／census 且 mutation=null，必須有 §3.0 unmapped 家族的 probe reason；家族 reason 配非 unmappable 不論 kind 都退件）；PARENT_SUMMARY 與每列的 `brief_revision` 必須一致（`brief_revision_mismatch`） | §2.1 CTRL_NEG、§3.0 選字規則、§5.1 schema（brief_revision enum、neighbours、replacement_provenance）、§5.1 mutation=null 規則 |
| (g) | 自寫 helper 只能放 `<batch>/helpers/`（對原檔唯讀、只開副本）；不得從 repo／批次目錄以外執行任何程式（pilot 從 OS temp 目錄跑 helper）；檔名列進 METHODS_AND_EVIDENCE_PLAN.md `## Helpers` | §1 helper 規則、§6 第 1 項、§7 |
| (h) | 自我驗證改用 `validate <batch> --out <batch>/VALIDATION.self.json --self-check`（只跳過 DONE.json 與 VALIDATION.self.json 兩條 presence 規則，輸出 `self_check: true`）；DONE.json 在最後一次 self-check 之後寫；Claude 的 ingest 不帶 `--self-check`（`self_check: false`） | §0.0、§6 第 8 項 |
| (i) | R7-1：`splice_kind ∈ {tj_item, tj_run}` 的增長證明以 `displacement_ink = Δ + K_sum·Tfs/1000` 定尺寸（K_sum = 這次 splice 新增或改變的 kern 總和），不是 Δ；`advance.displacement_ink` 必填欄位；`growth_pt`、verify bbox、experiment 的 `applicable` 都改以它計，收緊 kern 的誠實 F2G 不再被 0.5 pt after-vs-verify 誤退 | §3.3、§4 M4（advance 物件與 K 規則）、§5.1 schema advance 與 K token 規則、§5.1 applicable 規則、§5.2 growth_zone（applicable、after-vs-verify、growth_pt） |
| (j) | R7-2：`wrapper_stack[].tag` 不再對 Table-333 白名單比對，改為 ASCII PDF-name 字元集 fullmatch `[A-Za-z0-9_.-]{1,127}`（violation `client_string`，計入 `client_strings_left`；`TOCI`、`THead`、role-mapped producer tag 過；空字串、空白、`#`、非 ASCII 退件）；`props_name` 維持可印 ASCII 0x20–0x7E 規則（`props_name_not_ascii`） | §5.4 資料欄位掃描 |
| (k) | 標題 Grok Round Brief v3、`brief_revision: 3`、contract `true-text-case/2` 不變、HEAD 佔位規則不變、本節；§0.0 保留 pilot 模式開關（只跑三個 R0 控制組）讓 owner 能在 v3 下重跑一次 pilot；brief-v2.md 與 brief-v2-pilot.md 原樣保留為歷史 | 檔頭、§0.0、§8 |
| (l) | owner 決策 1–7（2026-10-24）寫入 §0.2 並落到各節：F18 拒絕（§3.6）、X5 暫緩與 F2 起點 F2I＋F2K（§3.3）、`standard_14_table`／`cmap_31_reverse` 接受、office-report-23p 登錄隨 I0a 落地所以本輪 census（§3.2／§3.3） | §0.2、§3.2、§3.3、§3.6 |
| (m) | V9：glyph_identity (b) 收窄為「同一 font xref 有該字的非目標出現處時才要求」；沒有出現處 → `consistency=null`、`gid_equals_consistency=null`，(b) 不適用，該字由 (a) 與獨立腿 (c) 判定，not_run 不再因 `consistency=null` 產生（`no_consistency_occurrence` 退場；null 以外的非物件值 → `consistency_malformed` not_run）。起因：`20261024_1803_r2` 的 CTRL_SYN_T0（替換字「再」「見」在單一 show 的合成頁別處不存在）在 §5.2 導語逐字要求 (b) 之下結構上無法九 phase 全 pass，與 §2.1 的固定 fixture／替換字衝突，校準 fail 經 §5.3 規則 4 讓全批控制與正例 insufficient_evidence；依 (c) 與 extraction 注意（字形正確由獨立腿證明）化解。此放寬不分 `brief_revision`（brief-v2 含同一衝突）。隨附三條收緊，只對 `brief_revision == 3`：`independent_leg.value` 定義為獨立腿推導出的字，`equals_char` 由 `value == char` 重算（不同 → `glyph_note_mismatch`，phase 依重算值判 `leg_char_differs`）；`char` 必須等於 `corpus_case.replacement[index]`（`glyph_identity_char`）；`consistency=null` 時 `gid_equals_consistency` 必須 null（`glyph_note_mismatch`）。schema 不變。1803 批次在修正後仍非綠（記成 not_run 的列變 `phase_result_mismatch`），須在 (m) 下重跑，不重新 ingest | §5.2 glyph_identity 導語、(b)、(c)、not_run 條件；§8 |
| (n) | V10：§5.1／§5.2 的三條 after-bbox 幾何檢查（`applicable=false` 時 after 比 target 在主邊寬 > 0.5 pt → `after_exceeds_target`；`applicable=true` 時 after 沒有長到 `growth_pt` → `after_not_grown`；after 超過 verify + 0.5 pt → `after_exceeds_verify`）在 `brief_revision 3` 下一律是 **growth_zone phase fail**（reason 如上，detail 記主邊延伸量 pt），不再是 bundle violation（v2 的 `growth_after_exceeds_target`／`growth_after_not_grown`／`growth_after_exceeds_verify` 只對 `brief_revision 2` 保留）；0.5 pt 門檻、到達條件、`growth_fields_not_null` 與 early return 不變。起因：`20261024_1803_r2` 的 CANARY_FONT（hvac p4 s11）誠實記錄 advance 相等（目標字型 /W）、`displacement_ink=0`、`applicable=false`，但換字型後 texttrace 的 after bbox 比 target 寬 6.09808 pt，Grok 記 growth_zone fail；v2 規則讓驗證器只發 `growth_after_exceeds_target` violation、phase 重算 pass → `phase_result_mismatch` + `calibration_mismatch`，而 R0 完整性要求 CANARY_FONT，所以每一次 full rev-3 R0 都被結構性退件。紀錄沒有自相矛盾，ink 落在沒被證明空白的帶子裡是保真事實（沒有增長時產品的 verify 框就是 target 框，`plan.py:2393-2394`），所以是 phase fail 不是退件；fail 擋住 §5.3 規則 5／6，status 走規則 7／8，永遠不是 pass。同時：CANARY_FONT 註記改為必記（§2.2）；product_commit 列走到此 fail 必列 `product_findings`（§5.2、§5.3 規則 8）；rederive 的 `_after_bound`（H1 鏡像）在 rev 3 只記 remeasured 延伸量、不隔離（說謊的 `after_bbox_raw` 仍由 `after_bbox_raw` 比對抓）。另記：§2.1 合成 sha 每次不同（E1）、§3.3／§0.2 F2R／F2G 不得因 X5 暫緩而不跑（g1）、§1／§7 舊批次文字不得 pipe 進直譯器（g2）、§5.2 not_run 條件補 `independent_leg` 缺少或非物件（n3） | §0.2 決策 2、§1、§2.1、§2.2、§3.3、§5.1 交叉規則、§5.2 growth_zone／glyph_identity、§5.3 規則 8、§7、§8 |
| (o) | V11：計畫列的 plan-schema violation 逐案歸屬（放寬，不分 `brief_revision`）。`METHODS_AND_EVIDENCE_PLAN.md` 裡 pointer 在 `/cases/<i>` 之下、且該列 class_id 是前沿類別的 violation，由驗證器記到每個 (class_id, slug, page_index, show_seq, variant) 與該列相同的 case（code、file、pointer 不變，補 case_id；那些 case 整案退件），該列照樣登錄；沒有 case 引用的前沿壞列降為 unverifiable `plan_row_invalid`；R0 校準列（class_id 為 CTRL_*／CANARY_*，或被 kind=control／canary 的 case 引用）、讀不出前沿類別的列、`/cases/<i>` 以外的計畫層 violation 仍是批次層——R0 是批次層前提（§2.3），不逐案化。起因：`20261024_2116_r2`（R0 校準通過，64 案）的計畫區塊有 8 列不合 schema——5 列 slug 照抄含 `.` 的 veraPDF PDF/UA 檔名（`/cases/28`、`/cases/34`–`37` 的 `slug`），3 列 E_F3S 自創 variant `split`（`/cases/52`–`54` 的 `variant`）——這 8 條 violation 沒有 case_id，rederive 依「不屬於任何 case 的 violation 汙染整批」整批拒收，其餘 56 案（14 R0 控制／canary + 42 前沿列，本 loop 第一批前沿量測）跟著被丟掉；brief-v2 第 750 行與本版 §6 第 1 項早就把預註冊的後果定為逐案，所以不分 `brief_revision`。同時寫清楚（驗證器不檢查、不改任何門檻）：§5.1 `slug` 的機械產生規則（與 rederive `_slugify` 相同）；§5.1 variant 詞彙封閉與 `eq`／`grow` 的意義（`grow` = advance 改變，變寬或縮短；2116 的三個 E_F3S 列 `displacement_ink` 都是負的）；§3.4 `fragment_split` 涵蓋縮短；§1 批次目錄只准五種副檔名 | §1 檔名規則、§3.4、§5.1 case_id／variant／slug、§6 第 1 項、§8 |

## 9. v4 變更紀錄
來自 `20261024_2116_r2`（第一次 full 批次，brief v3）28 列 `quarantined` 的 triage（`plans/v12-quarantine-triage.md`）。v4 的新規則只對 `brief_revision == 4` 生效（`item_range_bounds` 另對 `brief_revision == 3` 生效，因為所有 3.x 紀錄都是以索引語意寫的）；v4 紀錄繼承全部 v3 規則，brief-v3.md 原樣保留為歷史。

| id | 變更 | 觸及章節 |
|---|---|---|
| (p) | V12 目標粒度：`corpus_case.original`／`original_sha256` 是**目標切片**（整個 show 為目標時是整個 show）；新欄位 `corpus_case.show_text_sha256`（整個 show，每列必填）；`target.item_range` 是 TJ string item 的索引半開區間（v3 只在 schema 裡出現、沒有定義，Grok 寫索引、rederive 當 stream 位移讀）；`source_decode` 仍是整個 show；M1 在整個 show 的 run 內取切片子區間定位（`expected_origin_visual`、`target_bbox_*` 是切片的），probe 的 `target_text` 是切片，整個 show 另記為第二個視角 `probe.whole_show_max_tier_1`；`string_fragment`／`fragment_split` 的 `adv_old_text_space`／`adv_new_text_space` 是切片 `[b0, b1)` 與 `glyph_identity[]` code 的 advance（前綴／後綴不算）；鄰字配對的 `i = s + c0`；驗證器 `item_range_bounds`、`item_range_span`、`show_text_sha256_required`／`show_text_sha256_mismatch`；rederive 從原檔解出目標切片，不採信紀錄裡的目標文字 | §3.3、§3.4、§4 M0／M1、§5.1、§5.2 neighbours、schema |
| (q) | V13 定位失敗、`font_kind`、untracked origin：三個幾何欄位在 `origin_reliable == false` 時一起可為 null（schema 與驗證器 `geometry_on_untracked_origin`／`geometry_null_on_tracked_origin`／`geometry_partly_null`／`geometry_null_without_limit`），probe 用 `expected_origin=None`（「禁止換 origin 重試」的唯一例外）；M1 新增 positional 定位（texttrace unicode 為 U+FFFD／private-use、錨點唯一、`n` 個連續 glyph、`locate_method`）；`font_kind` 由 `/Subtype` 決定，與 CID codec 無關，沒有 codec 的 Type0 只做 census；rederive 把自己的定位失敗記成 `target_unlocatable`，不再當成產品例外 | §4 M1、§5.1、§5.2、schema |
| (r) | V14 canary 的 `changes[]`（澄清，沒有新規則）：canary 可以在字串 operand 前後帶 operator 插入（`Tc`、`Tf`、繪圖 operator）；形狀是「恰好一筆含 STRING／HEXSTRING 的 change、落在該 show 的 `[op_start, op_end]` 內，其餘都是零寬度、含 operator、不含字串的插入」；`advance` 描述的永遠只是那個字串 operand（`adv_old_text_space`、`adv_new_text_space`、`displacement*` 與 K 都以它為準，插入裡的數字不是 K）；`after_bbox_raw` 是以 before 的目標原點（< 0.02 pt）為錨取得的替換字形 bbox 聯集（min/max，空 bbox 也算），不是頁面上最近的同文字；CANARY_FONT／CANARY_WRONGGLYPH 的 after 字形與替換文字不同正是它們的目的，rederive 只記 `after_text_identity` 觀察值，不當 divergence | §5.1、§5.2 canary |
| (s) | V16 來源與登錄：驗證器新增 `relative_path_required`（public 與 local_unrecorded 的 `source.relative_path` 不得為 null）與 `slug_not_derived`（`source.slug` 必須等於 `_slugify(Path(relative_path).stem)`，與 rederive 的 registry 共用同一個函式）；兩條只對 `brief_revision == 4` 生效，2116（rev 3，local_unrecorded 的路徑是 null）與 1114（rev 2）的驗證結果不變。I0a 登錄：四個公開檔（isartor-6-3-7-t03-fail-a、isartor-6-3-2-t01-fail-a、veraPDF test suite 6-8-3-3-t01-fail-a、isartor-6-3-4-t01-fail-d；後者與已登錄的 -g 同一個 lineage，不是第二個）進 `public_corpus_sha256.json`，四個 local_unrecorded 檔進 manifest `corpora`，sha 都是對 owner 機器上的原檔重新計算的；`CorpusRegistry.by_sha` 的 provenance 過濾保留，所以 local_unrecorded 的登錄不能替宣告 public 的列背書。`before_pdf_mismatch` 除了「bundle before.pdf 的 sha 不符」，也表示「來源無法解析」（source unresolvable：沒有登錄且沒有可讀的路徑）；改名為獨立代碼延後，本輪只在文件裡寫明。| §3.0、§3.2、§3.5、§5.1 slug 與 relative_path、§5.4 |
| (t) | Q10／Q11：切片目標的 `growth_zone.background_bbox_visual`（收緊；單 item、F3、Tj 與沒有 kern 的整個 show 不變）。字型度量框從切片起點算、寬度扣掉切片內部的 kern：`(x_pre*Th, -0.35*Tfs, (x_pre + adv_old_text_space - K_inner/1000*Tfs)*Th, Tfs)`，`x_pre` = 切片之前所有 string item 的 advance（算法同 §5.1 的 adv_old），加上切片前每個 kern 數字 K 的 −K/1000·Tfs；F3 再加 item i0 裡 b0 之前位元組的 advance；整個 show 為目標時 `x_pre` = 第一個 string item 之前的 kern 總和的 −K/1000·Tfs（Tj 與無前置 kern 的 TJ 為 0）；`K_inner` = 切片內部、string item 之間的 kern 數字總和（切片之前的 kern 屬於 x_pre、切片之後的不算；單 item、F3、Tj 為 0；整個 show 為目標的 TJ 是所有 item 之間的 kern 總和）；沒有 kern 的整個 show（Tj）公式與產品 `_build_tier1` 相同。舊公式（原點 0.0、切片寬度）讓切片列的背景框落在 show 起點、涵蓋前綴字而不是切片，紀錄與 rederive 用同一個公式所以彼此對得上、看不出來；2116 有三列受影響，都由 deferred 變 quarantined(`remeasure`)：兩個 F2G `tj_run` 列（`f17a0919-p0-s4-grow1`、`f723638d-p0-s0-grow1`）的紀錄框比 `target_bbox_visual` 偏左約 393 pt，新公式的 x0 與 `target_bbox_visual` 差約 0.03 pt，x1 隨 Q11 再右移 K_inner 項（約 0.3 pt）；F2R `bdb495e9-p0-s2-eq1`（`item_range` [0,2]、x_pre 為 0、內部 kern 27）的紀錄框 x1 比 `target_bbox_visual` 寬約 0.32 pt，新公式的 x1 與它差約 0.002 pt（Q11）。驗證器不重算這個框（交給 rederive）；rederive 的 `x_pre` 算不出來（operand 無法解析、advance 無法證明）時期望值為 null，該欄位照舊是 divergence。`20261025_1824_r2`（第一個 v4 full 批次）的 README 指出 §5.1 growth_zone 那句還是舊公式（原點 0.0、寬 adv_old），該批次已照 (t) 算；§5.1 已同步改寫 | §5.1 切片目標的 advance、§5.1 growth_zone、§5.2 growth_zone |
| (u) | Q12：neighbours phase 的 `inshow_successor` 上限（`brief_revision >= 4`）從 1e-6 pt 改成 `(char_count_old + char_count_new)·Tfs·Th·trm_scale/1000 + 1e-6`，全部取自紀錄欄位（第一個 advance 物件的 `char_count_old`、`char_count_new`、`Tfs`、`Th`，加上 `target.trm_scale`，`trm_scale` 缺漏時當 1.0；其他欄位缺漏或無效一律退回 1e-6，不給預設值）；rev 2／3 不變。原因：MuPDF 把 simple font 的 `/Widths` 存成整數（四捨五入，CI 以 `test_q12_mupdf_integerises_fractional_widths` 釘住），產品卻用精確寬度算補償 kern K，每個字的前進差 `round(w) − w`（−0.5 到 +0.5 單位），所以改變字形多重集合的 F3 `fragment_split` 編輯會讓同一 show 內的後繼字差 Σ_new(round(w) − w) − Σ_old(round(w) − w) 個 /1000 單位；每個字最多 0.5 單位，上限取 1 單位，留 2 倍餘裕。`20261025_1824_r2` 的兩列 F3（`r2-F3-f723638d-p0-s7-grow1` 0.00109 pt、`r2-F3-bdb495e9-p0-s49-grow1` 0.00296 pt）只被這個 1e-6 上限判成 `probe_rejected`，在新規則下重算為 pass，所以重新驗證時會出現 `phase_result_mismatch`（紀錄的 neighbours 是 fail、重算是 pass），要等新的一輪才會消失。rederive 從 `/Widths` 重算精確殘差延後到 I0b（目前 rederive 不量 neighbours）| §5.2 neighbours |
| (v) | Q13：只動 rederive，Grok 的 probe 不變。census／negative 且三個幾何欄位為 null 的列，locate 失敗時，若紀錄的 show 是「多個」spell 目標位元組的 show 之一（不是唯一），仍以 `expected_origin=None` 跑 reason-only fallback probe，但只在產品回 `PlanRejection` 且 reason 是 `ambiguous_source_match` 時接受（產品只憑文字綁定，這個答案表示它什麼都沒綁到，不取決於紀錄指的是哪個 show）；prepared、其他 reason、例外一律維持 `target_unlocatable`。`remeasured.probe_fallback` 是 `reason_only`（唯一）或 `reason_only_shared`（共享），兩者在 `emit_rows` 都是 `geometry_unverifiable`、不產生 manifest 列。`20261025_1824_r2` 的 F17 `r2-F17-faefb744-p0-s28-cen1`（四個 show 同字）在此規則下 rederive 成 `rederived` | §4 M1 |

貼上時要告訴 Grok 的 V12 新定義（契約現在這樣寫，不是 Grok 違規）：`original` = 目標切片、`show_text_sha256`、`item_range` = 索引、切片定位與切片 probe、整個 show 第二視角。F2／F3 切片列、canary、`reason_order` 與五個公開檔 provenance 列的紀錄在新定義下本來就合規，不需要 Grok 更正。

貼上時要告訴 Grok 的 V13 新定義（契約現在這樣寫，不是 Grok 違規）：`origin_reliable == false` 的列三個幾何欄位寫 null、`limits[]` 說明、probe 用 `expected_origin=None`（唯一不算「換 origin 重試」的 probe）；texttrace unicode 讀不出來（U+FFFD／private-use）時的 positional 定位與 `locate_method: positional`；`font_kind` 看 `/Subtype`，不看 CID codec；沒有 CID codec 的 Type0 只做 census。2116 的 F30B（Wingdings）與 F5（Type3）兩列在新定義下本來就合規；F17 untracked origin 那列的幾何欄位在新規則下要寫 null（這是契約缺口，不是 Grok 違規）。

貼上時要告訴 Grok 的 V14 澄清（契約沒有新規則，原本的 canary 紀錄就合規）：canary 的 `changes[]` 可以帶 operator 插入，`advance` 只描述字串 operand 本身；`after_bbox_raw` 以 before 目標原點為錨取替換字形 bbox 聯集。TC、FONT、WRONGGLYPH 三列在這個定義下本來就合規，不需要 Grok 更正。

貼上時要告訴 Grok 的 V16 規則（`relative_path` 與 `slug`）：public 與 local_unrecorded 的列一律填 `source.relative_path`，只有 proprietary 與 synthetic 填 null；`source.slug` 必須等於 `relative_path` 檔名主幹的 `_slugify`（小寫、每段連續的 `[a-z0-9]` 以外字元換成一個 `-`、去頭尾 `-`）。2116 的 `vera-6-8-3-3-t01-fail-a` 是違反這條的紀錄（正確是 `verapdf-test-suite-6-8-3-3-t01-fail-a`），這是更正。四個 local_unrecorded 檔與四個新增的公開檔都已由 I0a 登錄，`20261025_1824_r2` 之後再登錄第五個公開檔 PDF/UA-2 `8.2.5.20-t02-pass-a`（sha `4a3bf064…`，lineage `vera-ua2-8-2-5-20-t02-pass`；該批次的 F1 列在登錄前的 checkout 是 `quarantined: provenance_unverified`）；在登錄之前的 checkout 預期 `quarantined: provenance_unverified`，仍會被重新量測。

貼上時要告訴 Grok（彙整，owner 貼 brief 時一併交代）：
1. 新定義（契約現在這樣寫，不是 Grok 違規）：`original` = 目標切片、`show_text_sha256`、`item_range` = 索引、M0／M1／鄰字配對對子 show 目標的切片定位、切片 probe 加整個 show 第二視角、`font_kind` 由 `/Subtype` 決定、`origin_reliable == false` 時三個幾何欄位寫 null、texttrace 讀不出來時的 positional 定位、canary 的 `changes[]` 可以帶 operator 插入且 `advance` 只描述字串 operand、local_unrecorded 的列要填 `relative_path`。
2. 更正（Grok 偏離了規則）：slug 必須是 `_slugify(stem)`（vera 那一列）；五個含 `.` 的 veraPDF slug；V11 的自創 variant `split`。
3. 刪掉的舊文字：「已登錄在 manifest」的舊說法（原 §3.0／§3.2／§3.5 三處）已改成「由 I0a 登錄；登錄之前預期 `quarantined: provenance_unverified`，仍會重新量測」。
4. 不需要 Grok 規則：F2／F3 切片列、canary、`reason_order` 與五個公開檔 provenance 列，它們的紀錄在新定義下本來就合規。
5. 新規則細節（契約現在這樣寫，不是違規；Grok 的 probe 與判定方式都不變，照產品實際回應記錄，不得為了過驗證改 probe）：(a) 切片目標的 `growth_zone.background_bbox_visual` 照 §9 (t) 的公式（字型度量框從切片起點算、寬度扣切片內部 kern）；(b) rev 4 的 neighbours `inshow_successor` 上限照 §9 (u)：MuPDF 把 simple font 的 `/Widths` 整數化，F3 `fragment_split` 會讓同 show 的後繼字有不超過 (char_count_old + char_count_new)/1000·Tfs 的殘差，這是量測到的事實，照實記錄 neighbours 結果；先前批次裡因舊的 1e-6 pt 上限而記成 `probe_rejected` 的 F3 列不需要更正；(c) Q13 只動 Claude 端 rederive，Grok 不用改任何東西。

## 10. v5 變更紀錄（2026-10-26，owner 已裁定：單一 runner 強制版、office-report-23p 登錄、F2K 保持開放）
來自 `20261026_0015_r2`（pilot）與 `20261026_0032_r2`（full）兩批的 triage；兩批在 HEAD 94d902f 都是 0 violation、rederive 0 divergence，所以 v5 **沒有**會改變 v4 紀錄 status 的新門檻。v5 規則只對 `brief_revision >= 5` 生效；0015／0032（rev 4）、2116 與 1713（rev 3）、1114（rev 2） 的驗證報告逐 byte 不變是 v5 驗證器提交的驗收條件。(x) 是本版唯一的放寬。

| id | 變更 | 觸及章節 |
|---|---|---|
| (w) | 單一 runner：同一批次所有列與 calibration 來自同一份 `run_pilot.py` 文字；runner／寫紀錄的 helper 只能在 §6 第 8 項的 self-check 迴圈內修改，改完在同戳記重跑整批 `--phase all`（算一次 R0 attempt）；混合 `--phase cases` 補跑為退件；bookkeeping helper 免除；`RUNS.json`（每一項格式必須正確；規則只檢查最後一項：phase 必須是 `all`、runner_sha256 必須等於記錄值 = PARENT_SUMMARY 的值）、每列與 PARENT_SUMMARY 的 `code_revision.runner_sha256`；驗證器 `runner_sha_missing`／`runner_sha_mixed`／`runner_sha_disk_mismatch`／`runs_missing`／`runs_malformed`／`runner_partial_rerun`（rev ≥ 5，皆批次層） | §6 第 2、4、8 項、§7、schema |
| (w2) | `distinct_lineages`／`distinct_producer_families`／single_family 只看 save_reopen_pass 正例；rev ≥ 5 驗證器改以正例計數（0032 的 F30B／F2I 由 Grok 記成 single_family 是對的，驗證器重算不是） | §3.0、§6 第 4 項 |
| (x) | **放寬**：驅動工具自己的指令包裝與輸出擷取可在 OS temp／使用者設定檔目錄；cwd 必須是 repo 根目錄、只執行批次內 run_pilot.py／helpers 與唯讀 git 指令、不得 inline 程式、批次程式不得讀它、README 保留一行揭露 | §1、§7 |
| (x2) | code_revision 時序：先建 `<batch>/` 並複製 runner／helpers，第一個指令 `--phase code_revision`；不再用 inline snippet；未追蹤的批次目錄不影響 `tracked_diff_empty` | §1 |
| (y) | F2K：要求不變（owner 保留）；0032 的有界掃描沒有可達 `tj_kern_in_tier1_range` 的形狀，crazyones 兩列被 `font_custom_differences` 擋在 F2K 閘之前；F2K 保持開放，I8 後重查；**2026-10-26 補充：0948 的 0 列、無新掃描是退件形狀，下一批 full 必須重掃並記錄（§3.3 v5 補充）** | §3.3 |
| (z) | 一次貼上 = 一個模式 = 一個戳記；pilot 通過後等 owner 貼 `mode: full`；README 第一行寫模式（step 0 的 blocked bundle 例外：第二行）；每戳記自己的 plan／runner 副本／helpers | §0.0 |
| (aa) | survey／locate 重查只開 `candidates/` 副本；0032 的 helpers/survey.py 開原檔 bytes 是程序偏離，列不受影響 | §1 |

貼上時要告訴 Grok（0015／0032 回饋）：
1. 兩批都通過：0 violation、calibration pass、rederive 0 divergence；Q12 的 neighbours 上限與 Q13 的 reason-only fallback 已在紀錄裡得到印證，不需要更正。
2. office-report-23p 已登錄（manifest `corpora`，本機檔名 `test_files/office-report-23p.pdf`，runner 以這個名字找它；列的 `relative_path` 仍寫 null）：0032 的 F1 p0 s25 census 列在新 registry 下 rederive 通過；F2I p0 s6 仍是 `quarantined: reason_order`，那是 Claude 端 rederive 的已知限制（整個 show 為目標的判定只認 kind=negative），不是 Grok 的問題，不要為此改紀錄。從 v5 起這個檔可做 positive／negative。
3. (w)：第一次執行後改 summary 邏輯是**正確的**，補跑 `--phase cases` 混入舊的 `--phase all` 列才是 v5 的退件形狀；以後改 runner 就在同戳記重跑整批。
4. (y)：F2K 不是「不必再掃」，而是保持開放；I8 落地後重查 crazyones 兩個 show。**0948 以「保持開放」為由 0 列、無新掃描，owner 2026-10-26 裁定不接受，見第 11 點。**
5. F5 test-complexed-layout p0 s0 這次沒有登錄，理由引用的是另一台機器的舊調查；下一批請在本機、在 `candidates/` 的副本上重做 locate 檢查並把結果寫進 README。
6. (aa)：survey.py 開原檔 bytes 當 PDF 是程序偏離；以後只開副本。
7. (x2)：code_revision 的 inline snippet 不是違規（契約缺口）；v5 起用 `--phase code_revision`。
8. CANARY_UNSAVED 在 rederive 永遠是 `skipped: canary_unsaved_handle_fault`（設計如此）。
9. Claude 的 rederive console 出現三行 MuPDF stderr（`FT_New_Memory_Face(RKAJXV+ArialMT)`），推測來自 isartor 6.3.2 t01-fail-a 的壞字型；F30W negative 列照常 rederive；不需處理。
10. 0927（pilot）與 0948（full）在 HEAD 3621f97 都通過：0 violation、calibration pass（6 控制組、8 canary）、rederive 0 divergence、0 quarantine；(w)／(w2)／(x2)／(z) 全部印證，`per_class` 計數與驗證器的正例重算一致，不需更正。
11. F2K（owner 裁定 2026-10-26）：0948 的 0 列、無新掃描不接受；下一批 full 照 §3.3 的 v5 補充在本機副本上重掃、把範圍與數字寫進 README，並讓 F2K 的 per_class 不為空。
12. office-report-23p：owner 裁定**不登錄 positive**（5.4 的理由成立），兩個 negative 列照 0948 繼續；整個 show 為目標的 census 列仍會 `quarantined: reason_order`（Claude 端限制 D22 維持，不為此改紀錄）。

## 11. v6 變更紀錄（2026-10-28，owner 已裁定：X5 成立、D22 解除、false-safe 歸屬表落地、KSIGN 第二站點；第 3 輪）
來自 `20261026_0948_r2`（full）與 `20261026_1050_r2`（full，補 F2K 重掃）兩批的 triage：兩批驗證 0 violation、calibration pass（驗證器規則自 v5 起未改），在 HEAD df3ec65（I0b S4：Claude 端 rederive 改跑六個 oracle）rederive 0 divergence、逐列比對 0 violation。v6 **沒有**會改變 v5 紀錄 status 的新門檻；驗證器只把 `brief_revision` enum 放寬到 6。

| id | 變更 | 觸及章節 |
|---|---|---|
| (ab) | `brief_revision: 6`；§5.1 schema 的 enum 加 6；驗證器**沒有**任何 rev-6 專屬規則；v5 以前的批次驗證結果逐位元組不變 | §0、§5.1 |
| (ac) | CANARY_KSIGN 第二站點（synthetic，必做）：CTRL_SYN_T1 的 before.pdf、`REPLACEMENT_SHORTER`、產品 Tier 1 commit（K ≈ −2000）、翻 K 正負號；must_fail 仍只有 structure，neighbours 預期同時 fail；hvac p4 s26 站點照舊 | §2.2 |
| (ad) | X5 成立：F2R／F2G 丟掉替換字內部 pair kern 算不跳；方法與記錄不變；I4／I5 落地前仍 measurement-only | §0.2、§3.3 |
| (ae) | D22 解除：整個 show 為目標、宣稱 `tj_multi_item_array` 的 census 列不再 `quarantined: reason_order`（Claude 端）；紀錄不變 | §0.2 |
| (af) | Claude 端 rederive 現在對每一列跑六個 oracle（growth、stream_range、wrapper、counts、neighbours、glyph_identity），報告多 `remeasured.neighbours`；Type1／CFF 簡單字型正例的 glyph_identity 沒有獨立腿 → `quarantined: oracle_assert_glyph_identity`，歸 I1，**不是 Grok 的缺陷**，照舊記錄 | 無（說明） |
| (ag) | F2K：1050 已補 crazyones 兩列 negative（p0 s16、s24，`probe_rejected`）；v5 (y)／第 11 點的要求維持：每個 full 批次 F2K 的 per_class 不得為空，掃描範圍與數字寫進 README | §3.3 |
| (ah) | 勘誤（2026-10-28，第 3 輪 full `20261028_0442_r2` 之後；Claude 端修正，Grok 的紀錄不用改）：(ab) 說「驗證器沒有任何規則變更」不成立——(ac) 的 synthetic KSIGN 站點在 hvac 在場時 `calibration_ref=not_applicable`，而 §2.3 那句 synthetic 白名單（CTRL_SYN_T0／T1、CANARY_GROWTH）沒有列它，驗證器因此對該列報 `synthetic_kind`（0442 唯一的 violation）。修正：`SYNTHETIC_CLASSES` 加入 `CANARY_KSIGN`（無條件；v5 以前的批次沒有這種列，報告逐位元組不變）。§2.3 那句自 v7 起讀作 class_id ∈ {CTRL_SYN_T0, CTRL_SYN_T1, CANARY_GROWTH, CANARY_KSIGN}。 | §2.3、§11 (ab) |

貼上時要告訴 Grok（0948／1050 回饋）：
1. 兩批都通過：0 violation、calibration pass（6 控制組、8 canary 全部 caught）、rederive 0 divergence。1050 = 0948 + 兩列 F2K negative；其餘每一列 status 完全相同。
2. Claude 端 rederive（df3ec65）：每批 30 列 rederived、5 列 quarantined（F30B×3、F30W×1、OUT×1，全部 `oracle_assert_glyph_identity`：Type1／CFF 程式沒有獨立 glyph 腿，I1 的 G1' 負責；**不需 Grok 更正**）。canary 對應：GROWTH→neighbours overlap（1、3 個字形）+growth、FONT→glyph font_changed+counts operators、WRONGGLYPH→glyph cid_program_cmap leg_char_differs、INK→neighbours ink_changed+counts、TC→counts、UNSAVED→skipped（設計如此）、KSIGN→六個 oracle 全 None（見 (ac)；驗證器的 structure 照樣抓到）。
3. (ac) 的理由：hvac p4 s26 是獨立 Tm 的 Tj，後面 188 個 show 沒有一個共用它的 pen，翻 K 只有 structure 抓得到；synthetic 站點讓鄰字腿也有證據。
4. F1 `r2-F1-f93735e1-p0-s4-eq1`（public）：你的 neighbours phase 記 `overlap_glyphs: 1`，Claude 端 oracle 同樣 1，產品兩個 tier 都拒絕（`mc_wrapper_not_pure_layer`），status `probe_rejected` 正確；不是產品缺陷，是實驗位元組的形狀，不用改。
5. F3 `r2-F3-bdb495e9-p0-s49-grow1`：Claude 端 neighbours 記 `ink_changed: 1 glyph(s)`、in-show 偏差 2.857e-05 pt。這是 Claude 端 helper 的已知形狀（in-show 後繼字形因 Q12 殘差跨過一個 raster bin），不是你的偏離，不用改紀錄；helper 修正在第 3 輪之後落地。
6. (ad)／(ae)／歸屬表：你的方法與紀錄都不用改。
7. 第 3 輪流程不變：先 `mode: pilot`（三個控制組），通過後等 owner 貼 `mode: full`；每戳記自己的 plan／runner 副本／helpers（v5 (z)）。

## 12. v7 變更紀錄（2026-10-28，沒有新的 owner 裁定；第 4 輪）
來自第 3 輪 pilot `20261028_0432_r2` 與 full `20261028_0442_r2` 的 triage。0432 乾淨；0442 是 Grok 在修好自己的 overlap 檢查後整批重跑的第 2 次嘗試（同一份 runner sha，parent 與 RUNS.json 最後一項一致）。v7 **沒有**會改變 v6 紀錄 status 的新門檻；驗證器只把 `brief_revision` enum 放寬到 7，v6 以前的批次驗證結果逐位元組不變。

| id | 變更 | 觸及章節 |
|---|---|---|
| (ai) | `brief_revision: 7`；§5.1 schema 的 enum 加 7；驗證器**沒有**任何 rev-7 專屬規則 | §0、§5.1 |
| (aj) | (ah) 的勘誤併入正文：§3.0 的 synthetic 白名單現在是 class_id ∈ {CTRL_SYN_T0, CTRL_SYN_T1, CANARY_GROWTH, CANARY_KSIGN}（驗證器 `SYNTHETIC_CLASSES` 無條件含 CANARY_KSIGN，85ee3b0）；§2.2 的 synthetic KSIGN 站點要求不變，仍是必做。0442 唯一的 violation `synthetic_kind` 因此消失，Grok 的紀錄不用改 | §2.2、§3.0 |
| (ak) | 沒有放寬、沒有新要求：驗證器尚未檢查 synthetic KSIGN 列的 `synthetic_builder.kwargs` 是否等於 CTRL_SYN_T1 的固定值，也尚未把它列為 R0 必備（兩者是 owner 待決的收緊，TODOS）。**照 (ac) 做就會過；不做或改 kwargs 會在之後的版本變成退件，請現在就照做** | §2.2 |

貼上時要告訴 Grok（0432／0442 回饋）：
1. 0432（pilot）乾淨；0442（full）在 85ee3b0 修正後驗證 ok=true、0 violation、calibration pass。
2. 0442 的唯一 violation 是 Claude 端驗證器漏列 CANARY_KSIGN（v6 (ac) 要求的 synthetic 站點被當成未授權 synthetic）；**不是 Grok 的缺陷**，列不用改。
3. Claude 端 rederive（26a1670 之後）：20 列 save_reopen_pass、31 列 probe_rejected、7 列 insufficient_evidence 皆重算一致，0 divergence；5 列 `quarantined: oracle_assert_glyph_identity`（F30B×3、F30W×1、OUT census×1；Type1／CFF 簡單字型沒有獨立 glyph 腿，歸 I1，**不需 Grok 更正**）；CANARY_UNSAVED 依設計 skipped；synthetic KSIGN 列由 neighbours 與 glyph_identity 配對抓到。
4. F3 `r2-F3-bdb495e9-p0-s49-grow1` 的 `ink_changed: 1 glyph(s)`（v6 回饋第 5 點）已由 Claude 端 helper 修正（I0b S5，26a1670：in-show 後繼字形改在預期位移處比對），現在 neighbours 為 None；Grok 的紀錄一直都不用改。
5. 方法、紀錄格式、模式流程不變：先 `mode: pilot`（三個控制組），通過後等 owner 貼 `mode: full`；每戳記自己的 plan／runner 副本／helpers（v5 (z)）。

---

## 13. v8 變更紀錄（2026-10-29，沒有新的 owner 裁定；第 5 輪）
來自第 4 輪 pilot `20261028_2228_r2` 與 full `20261029_0000_r2` 的 triage。兩批在 HEAD 158b1e9 都是 0 violation。v8 **沒有**新增 Grok 要做的事：它把 v7 (ak) 預告的兩個 CANARY_KSIGN 收緊寫成已生效的規則（Claude 端已於 46732a9 落地），並把 `brief_revision` enum 放寬到 8。`brief_revision <= 7` 的批次驗證結果逐位元組不變。

| id | 變更 | 觸及章節 |
|---|---|---|
| (al) | `brief_revision: 8`；§5.1 schema 的 enum 加 8；驗證器**沒有**任何 rev-8 專屬規則（下面兩條規則的門檻是 `brief_revision >= 7`，所以 v8 批次與 v7 批次受同樣檢查） | §0、§5.1 |
| (am) | (ak) 的預告生效，對 `brief_revision >= 7` 的紀錄與批次：（1）synthetic CANARY_KSIGN 列的 `synthetic_builder.kwargs` 必須逐字等於 `{"text": "你好世界", "rotate": 270, "tail_text": "後綴"}`（缺、null、非物件、任何不同的值都是 `synthetic_pin_mismatch`）；（2）hvac 在場時，批次必須同時有 synthetic 與 hvac 兩列 CANARY_KSIGN，缺哪一列 parent 都是 `calibration_incomplete`。**沒有新的要求**：照 (ac)／§2.2 做的 0000 兩條都過；現在不照做會被退件 | §2.2 |
| (an) | hvac 站點列必須是**非 synthetic** 的 hvac 列（CANARY_GROWTH 與 CANARY_KSIGN 兩者）：把 synthetic 列的 `source.slug` 寫成 `hvac` 不再同時算成兩個站點。synthetic 列的 slug 本來就是 `ctrl-syn`（§5.1），照做的紀錄不受影響；v8 之前的十四個批次驗證報告逐位元組不變 | §2.2 |
| (ao) | 說明，沒有放寬：hvac 站點的位置（p4 show 26）仍是 §2.2 的指示，驗證器**還沒**鎖定它（owner 待決的收緊，TODOS）。請照 §2.2 做，不要換位置 | §2.2 |
| (ap) | 說明（Claude 端，Grok 無動作）：wrapper oracle 現在能判定多變更列（CANARY_TC 三個變更、CANARY_FONT 三個、CANARY_INK 兩個），不再報 `unsupported:`；rederive 報告的 `remeasured.neighbours` 多一個覆蓋欄位 `glyphs_paired`（只在 rederive 報告，不在 bundle，不影響任何 status）；growth oracle 先 render 再抽取，與產品的呼叫順序一致。六十四列的 rederive outcome 與 0442 逐案相同 | 無（說明） |

貼上時要告訴 Grok（2228／0000 回饋）：
1. 2228（pilot）乾淨：0 violation，三個控制組 rederive 都 rederived、0 quarantine。0000（full，64 案）驗證 ok、0 violation、calibration pass，252 列 unverifiable（與 0442 相同的九種原因）；你的 `VALIDATION.self.json` 與 Claude 端驗證結果一致。
2. (am) 的兩條規則在 0000 上通過：synthetic KSIGN 列的 kwargs 與固定值一致，hvac 的 KSIGN 列（p4 s26）也在。`synthetic_kind` 沒有再出現。
3. Claude 端 rederive（0000）：58 列 rederived、1 列 skipped（CANARY_UNSAVED，依設計）、5 列 quarantined（F30B×3、F30W×1、OUT census×1，全部 `oracle_assert_glyph_identity`，歸 I1，**不需 Grok 更正**）；逐案與 0442 相同。
4. (ap) 是 Claude 端的測量變更，**不需要**更正任何紀錄。
5. 方法、紀錄格式、模式流程不變：先 `mode: pilot`（三個控制組），通過後等 owner 貼 `mode: full`；每戳記自己的 plan／runner 副本／helpers（v5 (z)）。

---

## 14. v9 變更紀錄（2026-10-29，沒有新的 owner 裁定；第 6 輪）
來自第 5 輪 pilot `20261029_1308_r2` 與 full `20261029_1809_r2` 的 triage。兩批（HEAD 分別是 d195609 與 ddf5f9e）都是 0 violation。v9 **沒有**新增 Grok 要做的事：它把 v8 (ao) 之後在 Claude 端落地的 `ksign_canary_site` 寫成已生效的規則，更正 `sh_operator_present` 的量測寫法（產品的 shading 掃描改成 token-aware，48d0d29），並把 `brief_revision` enum 放寬到 9。`brief_revision <= 8` 的批次驗證結果逐位元組不變。

| id | 變更 | 觸及章節 |
|---|---|---|
| (aq) | `brief_revision: 9`；§5.1 schema 的 enum 加 9；驗證器**沒有**任何 rev-9 專屬規則（`ksign_canary_site` 的門檻是 `brief_revision >= 8`，所以 v9 批次與 v8 批次受同樣檢查） | §0、§5.1 |
| (ar) | **取代 v8 (ao)**。(ao) 說驗證器還沒鎖定 hvac 站點的位置；現在鎖了（48d0d29）：對 `brief_revision >= 8` 的**非 synthetic** hvac CANARY_KSIGN 列，`corpus_case.page_index` 必須是 4、`corpus_case.show_seq` 必須是 26（CTRL_POS_T1 的站點，§2.2 的指示），兩個欄位**各自**比對，各自不符各算一個 `ksign_canary_site` violation。每列看自己的 `brief_revision`，不看批次。**沒有新的要求**：照 §2.2 做的 `20261029_1809_r2` 通過；不照做會被退件。synthetic 站點列不受影響 | §2.2 |
| (as) | 勘誤（Claude 端修正，Grok 的既有紀錄不用改）：v2–v8 的 §5.2 把 `sh_operator_present` 寫成「與產品 `_shading_presence` 同規則」並引用 `verify.py:1259-1264`，意思是「任一處有 `sh`」。產品的 shading 掃描已改成**頁級 token-aware**（`_page_has_shading_operator`）：字串、註解、名稱裡的 `sh` 不再讓產品拒絕。照舊寫法量測會比產品嚴，驗證器對這種列（pre-edit 頁只有字串／註解／名稱內的 `sh`）會報 `shading_operator`，產品卻會 commit。§5.2 的該條已改寫成新規則；請照新寫法量測。影響面：目前所有批次（十六個、479 筆紀錄）沒有任何一筆 `sh_operator_present` 為 true，所以沒有既有紀錄會改變 | §5.2 |
| (at) | 說明（Claude 端，Grok 無動作）：（1）rederive 的 `_replay` 排序鍵改為 `(stream_xref, start, end_old)`，同一個 stream 內同起點的變更不再互相造成 `end_new` 假分歧；（2）兩個過時的 widget 探測測試改成量產品實際讀的來源（產品的 fail-closed 行為沒變）；（3）上述全部在 `20261029_1809_r2` 上零 churn：rederive 與 emit 的形狀與 0000 逐案相同 | 無（說明） |

貼上時要告訴 Grok（1308／1809 回饋）：
1. 1308（pilot）乾淨：0 violation，三個控制組都 rederived、0 quarantine。1809（full，64 案，全部 `brief_revision: 8`）驗證 ok、0 violation，252 列 unverifiable（與 0000 相同的九種原因，數量也相同）；你的 `VALIDATION.self.json` 與 Claude 端驗證結果一致。
2. (ar) 在 1809 上通過：hvac 的 CANARY_KSIGN 列在 p4 s26，兩個欄位都對。這是這條規則第一次在真實的 rev-8 批次上執行。
3. Claude 端 rederive（1809）：58 列 rederived、1 列 skipped（CANARY_UNSAVED，依設計）、5 列 quarantined（F30B×3、F30W×1、OUT census×1，全部 `oracle_assert_glyph_identity`，歸 I1，**不需 Grok 更正**）；0 divergence，逐案與 0000 相同。唯一不同是四個 synthetic 案的 `case_id` 裡那段 slug hash（每個批次本來就不同），不是變更。
4. (as) 是量測寫法的更正：下一輪起，`sh_operator_present` 請照新寫法量；既有紀錄不用改。
5. (at) 是 Claude 端的測量變更，**不需要**更正任何紀錄。
6. 方法、紀錄格式、模式流程不變：先 `mode: pilot`（三個控制組），通過後等 owner 貼 `mode: full`；每戳記自己的 plan／runner 副本／helpers（v5 (z)）。


---

## 15. v10 變更紀錄（2026-10-29，owner：「ctrl-syn slug pin 補上」「寫 brief v10 = (au) slug pin 已生效 + mode: census 掃描指示」；第 7 輪）
來自第 6 輪 pilot `20261029_2145_r2` 與 full `20261029_2156_r2` 的 triage。兩批（HEAD 721f058）驗證都是 ok、0 violation。v10 給 Grok 的新動作只有一個新模式（census，§3.8）；pilot 與 full 的做法和 v9 相同。`brief_revision <= 9` 的批次驗證結果逐位元組不變（十九份驗證報告前後逐位元組相同）。

| id | 變更 | 觸及章節 |
|---|---|---|
| (au) | **synthetic 列的 slug 現在由驗證器強制。** `provenance=synthetic` 的紀錄，`source.slug` 必須是 `ctrl-syn`（§5.1 自 v3 起就這樣寫）；不符一個 `synthetic_slug` violation，pointer `/source/slug`。單向：非 synthetic 列不受影響（它們的 slug 仍由 `slug_not_derived` 管）。**不設 `brief_revision` 門檻**：有 synthetic 列的九個批次（rev 3 到 9）全部已是 `ctrl-syn`，所以**沒有新的要求**，照 §5.1 做的紀錄不受影響。這也堵住一個縫：把 synthetic 列的 slug 改寫成 `hvac`，不會再被當成 hvac 站點（v8 (an) 只在站點計數那一層擋住） | §2.2、§5.1 |
| (av) | `brief_revision: 10`；§5.1 schema 的 enum 加 10（case 與 parent）；驗證器**沒有**任何 rev-10 專屬規則（`ksign_canary_site` 仍是 `brief_revision >= 8`，兩條 KSIGN 第二站點規則仍是 `>= 7`，`synthetic_slug` 沒有門檻） | §0、§5.1 |
| (aw) | **新增 `mode: census`**（§0.0、§3.8）：唯讀的全語料普查，掃 `test_files/` 所有 PDF，每檔回報身分、文件與 show／字型的特徵計數。它**不是**案例批次：批次目錄是 `<stamp>_census`、只有 `run_census.py`、`CENSUS.json`、`README.md`、`DONE.json`，不經驗證器，不判斷、不推薦、不宣稱成功。pilot 與 full 完全不變 | §0.0、§3.8 |
| (ax) | 說明（Claude 端，Grok 無動作）：`20261029_0000_r2`、`20261029_1809_r2`、`20261029_2156_r2` 三個 full 批次的形狀完全相同（64 案；15 個公開檔 + hvac + synthetic；rederive 58 rederived／1 skipped／5 quarantined；252 列 unverifiable，同九種原因；emit 23 列）。同一份 §3 再跑只會得到同樣的報告，所以下一步改變輸入（census 找新候選），不是重跑 | 無（說明） |

貼上時要告訴 Grok（2145／2156 回饋）：
1. 2145（pilot）乾淨：0 violation，三個控制組都 rederived、0 quarantine。2156（full，64 案，全部 `brief_revision: 9`）驗證 ok、0 violation，252 列 unverifiable（與 0000、1809 相同的九種原因，數量也相同）；你的 `VALIDATION.self.json` 與 Claude 端驗證結果一致。
2. `ksign_canary_site` 在 rev 9 上通過；`sh_operator_present` 在所有紀錄都是 false。
3. Claude 端 rederive（2156）：58 列 rederived、1 列 skipped（CANARY_UNSAVED，依設計）、5 列 quarantined（F30B×3、F30W×1、OUT census×1，全部 `oracle_assert_glyph_identity`，歸 I1，**不需 Grok 更正**）；0 divergence，逐案與 1809、0000 相同；唯一不同是四個 synthetic 案的 `case_id` 裡那段 slug hash（每個批次本來就不同）。
4. (au) 沒有新的要求：你的 synthetic 列本來就是 `ctrl-syn`。
5. 下一次貼上是 `mode: census`（§3.8）：它不是案例批次，沒有 plan、cases、`VALIDATION.self.json`；只交 `run_census.py`、`CENSUS.json`、`README.md`、`DONE.json`。census 做完不要自行接著跑 pilot 或 full。
6. 方法、紀錄格式、pilot／full 的流程不變。


---

## 16. v11 變更紀錄（2026-10-30，owner：「v11 粗篩變細篩，不能提高上限的話就用等距抽頁」「`_evidence_pilot/*_census/` 加進 .gitignore」；第 7 輪續）
來自第一次普查 `20261030_0007_census` 的驗收（Claude 端）與兩份 §3.8 設計審查。第一次普查（HEAD 5bb4f54）：2,942 筆 = 磁碟上的 .pdf 數，`census_sha256` 相符，31 個欄位逐列齊全，與兩張登錄表逐檔對照 0 不符，驗證器第一層 denylist 掃描（31 條）掃過 6,907 個字串 0 命中。v11 只改 `mode: census`；pilot 與 full 的做法和 v10 相同，`brief_revision <= 10` 的批次驗證結果逐位元組不變。

| id | 變更 | 觸及章節 |
|---|---|---|
| (ay) | **抽頁：上限不變，取樣改成等距。** 每檔最多 50 頁，超過就等距抽（含首尾頁），不是前 50 頁。上限不能拿掉：語料裡有一個 10,000 頁的檔。前 50 頁只看得到封面與目錄 | §3.8 |
| (az) | **粗篩變細篩。** 每個檔帶 `census_show_shapes.census()` 的回傳（show 形狀 × 字型能力 × reject 原因）；v10 的文件層計數保留，改在同一組抽到的頁上算，並加不變量交叉驗證。replay 一律用預設預算（4 MiB），不傳 `None`；被拒絕或 malformed 的頁算進 `pages_replay_refused`／`pages_replay_malformed`，不再被讀成「這頁沒有字」。（`census()` 為此新增選用參數 `max_decoded_bytes`，預設 `None`，既有呼叫端行為不變） | §3.8 |
| (ba) | **欄位修正。** 新增每檔 `outcome`（enum）與 `exception_class`（v10 把它塞進 `limits` 裡的物件）；`producer_sha256` 定為 `{producer, creator}`、缺值 null；`producer_text` 只有 `public` 可寫（v10 讓 `local_unrecorded` 也寫，與 §5.4 矛盾）；**刪除 `producer_family`**（沒有機械規則，是判斷）；`relative_path` 寫登錄表裡的路徑並加 `path_matches_registry`；`local_unrecorded`／`proprietary` 的 `slug` 取 manifest `corpora[].slug` | §3.8 |
| (bb) | **措辭修正。** git 只准 §1 的唯讀指令（v10 轉述成「不得 git」是錯的，`code_revision` 本來就要用）；census 模式明文放寬「只開副本」，直接開原檔、禁一切寫入 API；§5 對 census 不適用、§3.8 明文引用的除外；README 第一行 `mode: census` 加進 §0.0 的模式列表；排序鍵定為 POSIX 相對路徑；`encrypted` 的 outcome（`needs_pass`，不 `authenticate`）與欄位（`is_encrypted`）分開定義；`doc.is_pdf` 為 false 算 `open_failed`；新增 `read_failed` | §0.0、§3.8 |
| (bc) | **外洩閘門。** census 不經驗證器，所以 `run_census.py` 自己掃：寫任何檔之前以 §5.4 第一層規則掃記憶體中的 CENSUS.json 與 README；`limits` 與 README 只准 ASCII 且不含檔名、路徑、producer；`run_census.py` 不得含 `test_files/` 底下的檔名；命中數記 `denylist_hits` | §3.8 |
| (bd) | **契約補強。** denylist 缺檔的停止形狀寫死（`blocked:` 在第一行、`census_sha256: null`、不寫 CENSUS.json）；單次執行不得續跑或拼接；寫入順序與 `"wb"` 位元組；三個 sha 都對讀回的磁碟位元組算；`DONE.json` 加 `readme_sha256`、`runner_sha256`；`CENSUS.json` 加 `tool_versions`、`sampling`、`replay_budget_bytes`，schema 改為 `true-text-census/2` | §3.8 |
| (be) | 說明（Claude 端，Grok 無動作）：`_evidence_pilot/*_census/` 已加入 `.gitignore`（CENSUS.json 以 hash 識別專有語料，不 commit）；因此 `run_census.py` 也不被追蹤，其身分由 `code_revision.runner_sha256` 與 `DONE.json` 的 `runner_sha256` 記錄。驗證器對 `brief_revision: 11` 的唯一改變是 enum 加 11，沒有 rev-11 專屬規則 | 無（說明） |

貼上時要告訴 Grok（`20261030_0007_census` 回饋）：
1. 第一次普查乾淨：2,942 筆、0 個 provenance 不符、0 個 denylist 命中、census_sha256 相符；你自己在 `limits` 寫的幾條限制（`producer_family` 沒有機械規則、outcome 放進 `files_detail`）都成立，v11 照你的處理方式寫成規則。
2. 這次每個檔要多帶 `census_show_shapes.census()` 的結果，replay 用預設預算；超過 50 頁的檔改成等距抽 50 頁（不是前 50 頁）；兩者與手寫計數用同一組頁。
3. 刪掉 `producer_family`；`producer_text` 只有 public 可寫；每檔加 `outcome` 與 `exception_class`；`limits` 只放 ASCII 字串、不放物件或檔名。
4. 可以直接開原檔、可以跑 §1 列出的唯讀 git 指令；仍然不得呼叫任何寫入 API，也不得複製 PDF。
5. 寫任何檔之前先用 denylist 掃自己的輸出；denylist 不存在時照 §3.8 的停止形狀（第一行 `blocked:`）。
6. 做完不要自行接著跑 pilot 或 full。
