# 專案真文字保真 skill

## Goal

建立專案共用 skill，以實際使用 PDF Editor 修改真文字後的字型、大小、位置一致為第一優先；TypeSafe 僅輔助證據判斷。此次只實作 skill 與入口，不修改 PDF 引擎、不啟動 Claude 實作、不呼叫付費推論。

## Modules

- `.agents/skills/pdf-text-fidelity/SKILL.md`：短入口與完成條件。
- 同目錄 `references/`：驗收方法、歷史證據索引、TypeSafe 契約。
- `.gitignore`：僅放行此 skill；其餘本地 agent 資料繼續忽略。
- `CLAUDE.md`：Codex / Claude 共用的適用情境與入口。
- `TODOS.md`：記錄 skill 完成與引擎未完成的區別。

## Steps and validation

1. [x] 讀取共享規則、skill-creator、typesafe-ai、現有實驗與測試紀錄。
2. [x] 建立修改前基線：尚無此專案 skill；已有實驗不等於正常 UI 編輯成功，既有測試紀錄仍為紅燈。
3. [x] 寫短入口與條件載入參考，保留 planning-only / implementation 範圍差異。
4. [x] 執行 skill validator、連結/可追蹤性/機器路徑檢查、全專案 ruff。
5. [x] 以獨立情境演練檢查錯誤完成宣告、自然字寬與 TypeSafe 失效處理；本地審查工具缺失分支。
6. [x] 記錄結果並歸檔；產品驗收仍留待引擎任務。

## Decisions

- 一份 canonical skill 放在 `.agents/skills/`，Claude 由 CLAUDE.md 讀取同一份，避免兩份規則漂移。
- 不把個人全域 typesafe-ai 改成 PDF 專用；專案規範可在未安裝該技能或無 API key 時運作。
- 此次是文件/指引變更，使用格式與行為演練驗證，不新增只匹配文件措辭的 pytest；不重跑約 108 秒的已知紅燈引擎測試冒充 skill 驗證。

## Dead ends / limits

- web 工具無法開啟 TypeSafe 文件，改用 Invoke-WebRequest 讀官方即時文件。
- 不能以 skill 已建立推論引擎已修好，亦不能聲稱已量測目標達成率提升。

## Validation results

- skill-creator `quick_validate.py`：Skill is valid。
- 4 個 skill Markdown、10 個本地連結存在；無尾端空白與機器身分路徑。
- `git check-ignore`：新 skill 可收錄，其他 `.agents` 私有檔及其他 skill 仍忽略。
- `git diff --check` 通過；全專案 `ruff check .` 通過。
- 唯讀獨立 agent 演練：規劃請求不啟動歷史 executor；engine 綠燈／成果顯示不代表 UI；自然字寬需核對邊界；TypeSafe .99 不覆蓋缺失證據；14 筆完成不需做向量；新真文字案例可納入。6 個情境均符合預期。
- 依演練修正兩點：矩陣改為當次授權案例集合；靠近邊界不能直接判成碰撞，須記錄幾何、間距及適用 gate，未知留白標準不得自行捏造。
- 反證審查：此規範本身不能保證 agent 永遠遵守，也尚非自動 hook。入口已明示；沒有 TypeSafe key 仍可完成本地工作，不把服務可用性變成 PDF 驗收前提。
- Jev 語言標準：自然語言指令、問題、criteria、候選標籤與證據摘要改為英文；原始 CJK 僅作 exact source data，並附英文 gloss，不讓翻譯取代原文核對。
- 此次沒有修改引擎、跑 UI、重跑產品 pytest/mypy 或呼叫 TypeSafe 模型；沒有 commit/push。只驗證 skill 文件與操作決策，未量測產品成功率改善。
