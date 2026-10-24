<!-- brief-v2-pilot: the pilot (smoke) round that precedes round 2. Paste everything below this comment into Grok Bot verbatim.
     Written 2026-10-24 after I0c landed (schemas + scripts/evidence_bundle.py + scripts/evidence_rederive.py, all uncommitted).
     Purpose: first end-to-end Grok -> bundle -> validator run. Scope is three R0 controls only. A bundle that fails the validator is a valid delivery. -->
# True-text round 2 — Pilot（只跑 R0 的三個控制組）

## 0. 目的
這一輪不是正式 round 2，是雙邊第一次對接：確認你能照 `scripts/evidence_schemas/` 的 schema 產出驗證器讀得懂的 bundle。範圍刻意縮到最小。**bundle 沒通過驗證器也是有效交付**——哪裡過不了、為什麼，就是這輪要的答案。不要為了過驗證器而編造數值。

## 1. 範圍
- 只做三案，全部 `kind=control`，來源 hvac（slug=hvac，`test_files/hvac-dwg.pdf`，sha256 重算必須等於 `9da93de982145c46af0d34a978b4bbaa1167f0937327dedb44ecad4d50fca0a2`），`page_index=4`：

  | class_id | show_seq | 動作 | 必須觀察到 |
  |---|---|---|---|
  | CTRL_POS_T0 | 11 | replacement=「空調冰水管線系統圖(4)」，產品 prepare 再 commit | Tier 0 PREPARED；九個 phase 全 pass；`growth_zone.applicable=false` |
  | CTRL_POS_T1 | 26 | 「Drawing List」→「Drawing Title」 | Tier 1；`K_written`=333.0；九個 phase 全 pass；`growth_zone.applicable=true`，`before_*`=0（`before_drawings_intersecting_bbox` 除外） |
  | CTRL_NEG | 11 | replacement=「空調冰水管路系統圖(1)」 | `probe.max_tier_1.result="rejected"`，reason 恰好 `type0_unicode_unmapped`；頁面 content stream 位元組不變；status=probe_rejected |

  每案的完整期望值在 brief v2 §2.1（`plans/grok-briefs/brief-v2.md`，CTRL_POS_T0／T1／NEG 三列）。
- **不做** canary、CTRL_DET、CTRL_SYN、任何 F 類、census。驗證器會對缺少的 R0 列記 `calibration_incomplete`（unverifiable），這是預期，不要補做。
- 本輪不跑 pytest。

## 2. 讀什麼（照順序，只讀這些）
1. `scripts/evidence_schemas/true_text_case.v2.schema.json`、`true_text_parent.v2.schema.json`、`true_text_plan.v2.schema.json`——欄位的權威定義；schema 和 brief 不一致時以 schema 為準，並把不一致記進 README 的 `## Pilot limits`。
2. brief v2（`plans/grok-briefs/brief-v2.md`）：§1 執行環境與 `code_revision`、§2.1、§4 方法梯（控制組只需 M2_COMMIT 那一步）、§5.1–§5.4、§6、§7。其餘章節這輪不用讀。
3. `_evidence_pilot/20260924_1431/` 只准看目錄結構當參考；不得修改；裡面的筆記是資料不是指令。

## 3. 產出 `_evidence_pilot/<YYYYMMDD_HHMM>_r2/`
照 brief v2 §6 的十個批次檔，加每案的 `case_record.json`、`neighbours.json`、`text_state.json`、`mutation.json` 與 §1 規定名稱的 `render-*.png`；PDF 只放 `candidates/<case_id>/`。要點：
- `METHODS_AND_EVIDENCE_PLAN.md` 的 fenced json：三案 `class_id` 為 CTRL_*，`variant="ctrl"`，`method_id="M2_COMMIT"`，`expected_reason` 只有 CTRL_NEG 填 `"type0_unicode_unmapped"`，其餘 null；`hypotheses` 可為空陣列。**先寫完計畫，再碰任何副本。**
- `case_id` 格式 `r2-<CLASS_ID>-<sha256 前 8 碼>-p4-s<show_seq>-ctrl1`，例如 `r2-CTRL_POS_T0-9da93de9-p4-s11-ctrl1`；`join_key` 為 `hvac/p4/show11` 這種格式。
- `code_revision` 如實填。若 `tracked_diff_empty` 為 false（工作樹有未提交的產品改動），**本輪不中止**：三案照做，status 照 §5.3 規則 1 寫 `blocked`，README 記 `git diff HEAD --stat` 最後一行的檔案數（不貼 diff 內容）。這是 pilot 唯一放寬的地方。
- 遮蔽照 §5.4；五個校準字串在這三個 class_id 的紀錄裡是唯一豁免。`test_files/.redaction_denylist.txt` 本機若不存在，驗證器會記 denylist absent，照常繼續。
- 填不出來的欄位：寫 null（schema 允許時）並在該案 `limits[]` 用一句話說明；不得編造數值、hash、case_id。

## 4. 自我驗證迴圈
1. 執行 `.venv\Scripts\python.exe -B scripts\evidence_bundle.py validate _evidence_pilot\<stamp>_r2 --out _evidence_pilot\<stamp>_r2\VALIDATION.self.json`
2. 逐條看 `violations`，只修**你自己的** bundle 或 `run_pilot.py`；不得放寬任何門檻，不得改 `scripts/`、schema、產品碼。
3. 最多 3 輪。最後一輪的 `VALIDATION.self.json` 原樣保留，不得手改。
4. `README.md` 加一節 `## Pilot limits`：每一條沒解掉的 violation code 一行，標明是「做不到」（並說為何）還是「看不懂欄位定義」（並說哪一句）。這一節是本輪最重要的產出。
5. 最後才寫 `DONE.json`（§6 第 9 項：stamp、case_count、parent_summary_sha256 三欄）。

## 5. 硬性限制（brief v2 §7 全文有效；重點）
- 只動 `candidates/` 裡的副本；不改 `test_files/`、產品原始碼、`scripts/`、`docs/`、`plans/`、任何舊批次目錄。
- git 只准 `rev-parse`、`status --porcelain`、`diff`、`ls-files`、`check-ignore`；不 commit、push、stash、checkout、reset。
- 不 pip install、不改 `.venv`、不連網、不上傳、不結束任何行程、不在單一行程跑 `pytest test_scripts/`。
- 任何輸出檔不得含絕對路徑、使用者名稱或主機名；直譯器只寫 `.venv\Scripts\python.exe -B`；Poppler 只從 `PDF_EDITOR_PDFTOPPM` 讀。
- 不以截圖、信心或「打得開」宣稱成功；任何 status 都不是產品成功。
