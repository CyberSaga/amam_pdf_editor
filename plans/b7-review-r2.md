## Result

**Part A　尚不宜接上正式 `vector_delete`。** 已確認顯式 lease 會核對持有人、新查詢不再沿用另一個 index 的選取、`skipped` 隨 token 保存。仍有三條可能影響文件正確性的路徑：commit 以 `None` 回報失敗卻觸發 OCR drain、OCR 用結果送達時的頁面替辨識快照作證，以及允許通過 busy guard 的導航仍可讀取交易中的 live document。

**Part B　`CLIPPED` 可採單一矩形證明，但應先量出實際新增的可移動列。** 每列須同時具備來源墨跡證明與可供目的地重驗的裁切證據。只清旗標會讓後續 move 失去約束。[b7-clipped-design-draft.md:8](C:/Users/wilson/Documents/amam_pdf_editor/plans/b7-clipped-design-draft.md:8)

## Part A　第一輪修正核對

| 項目 | 第二輪判定 |
|---|---|
| `write_transaction()` 失敗路徑 | **只修到例外外拋。** `except BaseException` 釋放 lease 並保留佇列。但 `commit_delete()` 遇拒絕、已 rollback，甚至 rollback 驗證失敗，都可能回 `None`。呼叫端若在 `with` 內 `return`，仍會走正常離開並 drain。after-capture 拋錯也只會放鎖，無人復原已成功的刪除；`record()` 又先改 revision、append，再 dedup／trim。應由持有人明確發布，區分成功、已驗證還原、狀態不確定。最後一種須保留現場及 OCR，阻止後續自動寫入。成功路徑維持 Plan A，derived index 在 `record()` 後按新 revision 重綁。`model/pdf_model.py:4400`、`model/vector_paths/commit.py:228`、`model/vector_paths/commit.py:236`、`model/vector_paths/commit.py:255`、`model/edit_commands.py:1462`、`test_scripts/test_vector_write_gate.py:294` |
| `holds()` 與 lease 傳遞 | **持有人身分已修。** released／foreign lease 即使碰到空閒 gate 也會拒絕。剩餘問題是 `gated()` 取出 `write_lease` 後不再傳遞，合法持有人走 `save_session_as → save_as` 仍會被內層拒絕。一般 writer 只 `check()`，沒有覆蓋整筆操作；無顯式 lease 的 commit 只持有到 T1 返回，期間排入的 OCR 可被下一筆立即送達的 OCR 超前。`CommandManager` 也只在 getter 綁 gate，`clear()`、`mark_saved()` 仍可改 history 狀態。`model/write_gate.py:64`、`model/write_gate.py:137`、`model/pdf_model.py:884`、`model/pdf_model.py:1423`、`model/pdf_model.py:4392`、`model/edit_commands.py:1548`、`model/edit_commands.py:1584` |
| OCR page key | **能偵測入列後旋轉，無法證明辨識的是這一頁。** Worker 收到 snapshot bytes，回傳只有 `gen, page_num, spans`。若同一 job、同一 session 在辨識期間換頁，結果送達後才讀到的 xref／幾何已屬新頁；空閒時更直接套用。現有 key 把座標四捨五入至三位，亦無法區分同 xref、同框但內容已換的頁。應在取得辨識快照時綁定邏輯頁身分、來源版本及精確 frame，隨結果傳回；以 `(session, job, sequence)` 去重，立即與延後路徑都驗。現有「replaced」測例實際只在入列後旋轉。`controller/ocr_coordinator.py:90`、`controller/ocr_coordinator.py:194`、`controller/ocr_coordinator.py:271`、`model/pdf_model.py:4409`、`model/pdf_model.py:4422`、`test_scripts/test_vector_write_gate.py:343` |
| `on_ocr_applied` | **正式接線已存在，但通知有重複與漏報。** `activate → connect_bridge → attach_model_hook` 接上了 Model 自動 drain。立即成功時 Model hook 與 coordinator 各清一次 cache；明確呼叫 coordinator drain 也會在逐頁通知後再清一次。目前清 cache 只是設 `None`。較嚴重的是寫入文字後 `rebuild_page()` 拋錯會轉為 `Stale`，不通知；drain 已先移走整批，hook 拋錯也可能丟失後續頁。應逐 UI turn 處理一頁，成功確認後才出列，由一處通知實際寫入，對部分寫入復原或保留待處置，並更新 OCR dirty 狀態。`controller/pdf_controller.py:441`、`controller/ocr_coordinator.py:153`、`controller/ocr_coordinator.py:284`、`controller/ocr_coordinator.py:295`、`model/pdf_model.py:4252`、`model/pdf_model.py:4272`、`model/pdf_model.py:4439`、`model/pdf_model.py:4455`、`model/pdf_model.py:818` |
| 跨 index 選取 | **`add/toggle` 已修，舊讀取入口仍會借錯。** `vector_select()` 比對頁碼、index 物件、handle；commit 也驗 token 與 index。但換裝等長 index 後、下一次查詢前，`vector_selection_segments()` 直接把舊 mask 套在新表上，可能畫出另一物件；列數不同則可能因形狀錯誤失敗。`vector_selection_mask()` 直接交出可寫的舊 mask。應讓 mask、segments、presentation、plan 共用同一個驗證入口，綁定 session／handle／revision／index／token，回傳唯讀 mask 或副本。DTO 仍缺 `session_id`。`model/pdf_model.py:4501`、`model/pdf_model.py:4538`、`model/pdf_model.py:4570`、`model/pdf_model.py:4593`、`model/vector_paths/commit.py:82`、`utils/vector_selection_dto.py:35` |
| `skipped` 與 `all` | **本輪主修正成立。** `skipped` 描述本次 query，`count` 描述 combine 後的集合；Info 與 presentation 取同一 token 的值。`all` 已改走 `select_counting_skipped()`。仍建議補 Model 層的 `all`、`clear`、空白 `add` 同 token 對照；目前新增的 Info／DTO 測例只走 `touch`。另有具體邊界：`all` 用 ±`1e30` 模擬無界，而 scanner 接受 float32 範圍，`contain` 又要求 `seg_count > 0`。可直接以全列 eligibility/countable 遮罩實作 `all`，明訂純點列資格。`model/pdf_model.py:4527`、`model/pdf_model.py:4543`、`model/pdf_model.py:4599`、`model/vector_paths/index.py:135`、`model/vector_paths/scan.py:51`、`test_scripts/test_vector_movable_subset.py:171` |
| `_READ_ONLY_SLOTS` | **縮表有效，仍有可達的 live read。** `jump_to_result()` 可落到 `get_page_pixmap()`；`change_page → show_page` 同樣有同步 render；DPR／viewport 回呼也可啟動 render。測試放行的是同名區域函式。允許重畫已發布 pixmap，cache miss、timer 建索引及 worker completion 發布則應延後並重新驗身分。旋轉頁的文字讀取甚至暫寫 `/Rotate`。關窗仍在入口先取消 worker，CLI 仍能直接 `open_pdf()`；busy 拒絕註解顯隱時也須同步還原 QAction 勾選。`controller/pdf_controller.py:601`、`controller/pdf_controller.py:1843`、`controller/pdf_controller.py:5173`、`controller/pdf_controller.py:5350`、`controller/pdf_controller.py:5374`、`controller/pdf_controller.py:6478`、`controller/pdf_controller.py:2106`、`model/page_content_text.py:76`、`view/pdf_view.py:1766`、`test_scripts/test_vector_write_gate_controller.py:35` |

### `_query_cache` 的生命週期與記憶體

換成**新的** `VectorIndex` 物件不會沿用舊 `_query_cache`。真正的失效條件是**相同物件的來源陣列被修改**：`VectorIndex` 與 `paths` 都可寫，transport 測試也真的改寫載入後的 `flags`。第一次查詢後若再解析資源、修旗標、替換 `bbox` 或筆寬，cached eligibility／click 與即時讀出的 flags 便可能互相矛盾。另有舊 selection 強引用已被淘汰的 index，從 cache dict 移除不一定釋放記憶體。`model/vector_paths/index.py:31`、`model/vector_paths/index.py:184`、`model/vector_paths/scan.py:214`、`test_scripts/test_vector_scan_child.py:67`、`model/pdf_model.py:4543`

**建議由 `install_vector_index()` 負責接收已完成、可發布的查詢資料，以及核算容量。** 順序為驗來源身分 → 完成資源／flags 解析 → 固定基礎表所有權並凍結 → 建立唯讀衍生陣列 → 按 resident bytes 淘汰及發布。若建表放在 load worker，安裝時再次驗身分即可。直接查詢未安裝 index 的既有 API 可保留延遲建表，但須遵守同一不可變契約。不要只把首次配置從 click 搬到 GUI 安裝回呼。

目前完整暖機約 **53 B／列**：bbox 32、paint code 8、半寬 8、五個 bool 5。414,510 列約 **21.0 MiB／index**，另有建表暫存。`_VECTOR_CACHE_BYTES` 只加總 `index.nbytes`，且單一 index 有保留例外；transport 又要求 `nbytes` 等於序列化表長總和。因此另設 resident 成本，勿直接改寫 transport 的 `nbytes`。進度檔記載 CAD 最大 33.2 ms，尚不能據此判定密集點及 countable fall-through 都通過 50 ms。`model/vector_paths/index.py:40`、`model/vector_paths/index.py:104`、`model/vector_paths/index.py:184`、`model/vector_paths/index.py:214`、`model/pdf_model.py:4485`、`model/vector_paths/transport.py:206`、`plans/b7-progress.md:22`、`TODOS.md:4`

### 類別層級的 write gate 檢查

**清冊仍是手列。** `resize_object` 已補入；安裝器只包清單上的名稱。現有測試從 `REFUSAL_CALLS` 或 `GATED_TOOL_METHODS` 起跑，額外的 AST 掃描只找 `PDFModel` 內的 `edit_count +=`。例如 `WatermarkTool.on_session_open()` 可以沿 `_take_back_saved_copies → strip_marked_watermarks` 改傳入文件，不在工具清冊；呼叫時須區別 live doc 與尚未發布的私有 doc。`model/write_gate.py:92`、`model/write_gate.py:120`、`model/write_gate.py:150`、`model/tools/watermark_tool.py:131`、`model/tools/watermark_tool.py:168`、`test_scripts/test_vector_write_gate.py:177`、`test_scripts/test_vector_write_gate.py:224`

建議在 `test_scripts/test_vector_write_gate.py` 加一個可找出**遺漏入口**的參數化契約測試。

1. 從 `PDFModel`、`ToolManager` 及實際註冊的各 extension class 枚舉公開方法、繼承方法及可寫 property。從每個入口沿 `self`、delegate、import alias、free function 追到 `fitz.Document/Page/Annot/Shape` 與 repo 的底層寫入 helper。未解析的動態分派、或新增入口無有效測例時，列出 `class.method → 未覆蓋分支` 並讓測試失敗。
2. 用兩頁真實文件及有效參數建立 fixture，包含旋轉頁、annotation、可 resize 物件、已烘焙 watermark、非空 history。第一遍在空閒 gate 順利執行，用可透傳的 mutator spy 記錄第一次操作的 receiver、所屬 doc 及方法；同時比對 xref／stream、tool state、session、history、輸出檔。私有 clone 與 live handle 分別記錄。無效參數、提前返回、全 mock 不能構成 writer 的正控制。
3. 從同一前態重建 fixture，由另一個持有人取 lease，**直接呼叫同一公開入口**。一般 writer 須在第一次 live mutator、snapshot 或 tool/history 副作用前回 `WriteGateBusy`；OCR 只容許 `Deferred` 與佇列變化。加一條巢狀合法 lease 的成功對照。以移除 `resize_object` guard 作突變控制，測試必須報出入口及命中的底層操作。另測暫寫後還原的 `/Rotate`，最終 bytes 相等也得抓到。`model/write_gate.py:107`、`model/pdf_model.py:884`、`model/tools/annotation_tool.py:582`、`model/page_content_text.py:92`

## Part B　`CLIPPED` 完整設計

### 1. 先量 CAD 語料的可移動增益

以下是 **B5 已記錄的基線**，沒有在本輪重測。五個案例是四份檔案、五個頁面。[b5-fill-topology-clipped-design.md:53](C:/Users/wilson/Documents/amam_pdf_editor/plans/b5-fill-topology-clipped-design.md:53)

| 檔案／頁，頁碼自 1 起 | rows | `CLIPPED` | 基線可移動 |
|---|---:|---:|---:|
| `cad_vector/before.pdf` 1 | 414,510 | 0 | 414,510 |
| `ecc-dwg.pdf` 1 | 4,063 | 4,056 | 0 |
| `hvac-dwg.pdf` 1 | 421 | 167 | 198 |
| `hvac-dwg.pdf` 6 | 24,745 | 24,734 | 0 |
| `22060_A1_01_Plans.pdf` 1 | 53 | 51 | 1 |

先以不改 flags 的診斷掃描，逐頁記錄 hash、頁碼、frame、scanner、已索引範圍。將舊 `CLIPPED` 列依序分成「整條有效裁切鏈可證為矩形」「扣除其他 blocker 後可編輯」「有有限墨跡界」「來源嚴格內含」「存在可表示的非零安全位移」。每欄列**筆數、分母及失敗原因**；另列 setter 形狀、巢狀深度、到最近邊界的餘量，以及各方向可移動距離。分開報每頁與總計，`before.pdf` 的裁切覆蓋率填不適用。

這個先後順序會影響是否值得實作。ECC 的 4,056 列另有 `IN_OC`；HVAC 第一個 clip 距頁邊僅約 `0.000008871 pt`。優先查看 `22060_A1_01_Plans.pdf` 的 51 列是否真的能取得位移，再看 HVAC 的主要拒絕原因。若五頁實際新增可移動列均為零，保留診斷結果，停止擴寫 F 與 transport；任何多邊形放寬另憑語料決定。[b5-fill-topology-clipped-design.md:59](C:/Users/wilson/Documents/amam_pdf_editor/plans/b5-fill-topology-clipped-design.md:59) [b5-fill-topology-clipped-design.md:63](C:/Users/wilson/Documents/amam_pdf_editor/plans/b5-fill-topology-clipped-design.md:63)

### 2. Scanner 狀態與運算順序

- 狀態為 `Unbounded | Rect(x0,y0,x1,y1) | Empty | Unknown`，座標統一用未旋轉頁面空間。`Unbounded` 表示沒有受追蹤的顯式 clip；不從六個 frame 數字推算 CropBox。`q` 保存、`Q` 恢復；相鄰 `/Contents` stream 延續狀態。
- `W/W*` 只設 pending。終止 paint（包括 `n`）先用**舊** clip 處理該列，setter 保留 `SETS_CLIP`，再更新後續列的有效交集。無 path 的 `W n` 仍產生裁切事件，即使沒有 row。文字在 `Tr=4..7` 下實際顯示字元才累積 text clip，至有效 `ET` 轉為 `Unknown`；空字串、只含數字的 `TJ`、`Q`、巢狀 `BT` 沿用已有 renderer 對照語意。`model/vector_paths/scan.py:742`、`model/vector_paths/scan.py:770`、`model/vector_paths/scan.py:801`、`model/vector_paths/scan.py:902`、`model/vector_paths/scan_fast.py:790`、`test_scripts/test_vector_scan.py:1456`
- 首版只接受**恰一個非退化 `re`**，無額外 contour，構造時 CTM 可證一致。以 `CTM ∘ frame` 的實際映射驗證軸平行，接受負寬高、反射、精確四分之一轉；驗證後才將角點排序。不可用 epsilon 把微斜矩形吸附到座標軸。多 contour、洞、曲線、菱形、shear、構造中換 CTM、來源不明都給 `Unknown`。可確證無面積的裁切給 `Empty`。
- `Rect ∩ Rect` 取交集；邊界相觸或分離為 `Empty`。`Empty` 在該 scope 內保持空；`Unknown` 遇後來的有效矩形仍不能升為已知。`Q` 恢復父狀態。對 malformed input、`BI` 截斷、scope 不完整，維持既有拒絕或已驗前綴，不跨缺口發證。`model/vector_paths/scan.py:790`、`model/vector_paths/scan.py:810`、`model/vector_paths/scan.py:1019`、`plans/b5-fill-topology-clipped-design.md:65`

### 3. 墨跡界與目的地條件

令 `B` 為所有相關 subpath 端點、Bézier 控制點、隱式閉合線端點及退化筆畫中心經構造變換後的外包矩形。曲線位於控制點凸包內，因此 fill 可用 `B`。從原始 primitive 求界，避免 flatten 後的 chord 漏掉曲線凸出部分。`model/vector_paths/scan.py:915`、`model/vector_paths/scan.py:944`、`model/vector_paths/scan.py:962`

對 stroke，令 `A` 為筆畫到同一頁面空間的線性變換、`w` 為有效筆寬、`M` 為有效 miter limit。首版採保守半徑 **`r = |w| × σmax(A) / 2 × max(1, √2, M)`**，墨跡界為 `B` 四側各擴 `r`。這涵蓋圓帽、方帽、join、虛線端帽及尖 miter；fill+stroke 取兩界聯集。追蹤 `w/J/j/M`、PDF 預設值及 `q/Q`；`gs` 後不能證明所需狀態時，stroke 保留 blocker。hairline、無可靠界的 device stroke adjustment、非法參數、奇異或非有限變換均不發證。已有 page-space `line_width` 時避免再乘一次 `σmax`。`model/vector_paths/scan.py:16`、`model/vector_paths/scan.py:733`、`model/vector_paths/scan.py:998`、`model/vector_paths/scan.py:1076`

墨跡下界向外、clip 下界向內取整，上界方向相反；包含變換、筆寬及位移序列化的數值誤差。單在最後做一次 `nextafter` 無法替長串 CTM 證明累積誤差；誤差包絡不可靠即保留 `CLIPPED`。來源須在四邊皆**嚴格內含**。實際 move 將視覺 delta 轉至同一未旋轉座標，以**實際會寫入的 `cm` 運算元**重算目的地，亦須嚴格內含同一個固定 clip。不得移動含 setter 的外層 `cm` 或整個 scope。既有固定列留在原位；本次欲移動的子集中，只要一列越界，整筆拒絕，文件、history、token 均維持原狀。`model/pdf_content_ops.py:122`、`plans/cad-vector-object-editing.md:331`、`plans/b7-design-astra.md:78`

### 4. 可傳輸的證據與 G/F 一致性

| 表／狀態 | 契約 |
|---|---|
| `clip_rects` | 稀疏、定長 little-endian float64 四元組；依首次使用順序為有效交集矩形編號，共用相同矩形。儲存向內取整後的界。 |
| `clip_limits` | 每個取得豁免的 path 恰一列，含 `path:int32`、`rect_id:int32`、`ink_bbox:float64[4]`，按 path 嚴格遞增。來源墨跡界向外取整。無裁切頁兩表皆空。 |
| flags 與身分 | 建議保留「曾受顯式 clip」的可驗資訊，讓 move 只對有唯一有效證據的列解除 `CLIPPED` 阻擋。若採草稿直接清位，須另存受限標記，防止缺表被解讀成無界。`SETS_CLIP`、`PAGE_ANCHORED`、`IN_OC` 等獨立 blocker 照常生效。證據綁定 stream digest、frame、index 及發布 revision；重掃衍生 index 重新發證。 |
| transport | 分配前驗 schema、`count × itemsize`、總大小與上限；載入後驗 ID、有限值、順序、唯一性、flags 對應、矩形非空及來源嚴格內含。缺表、重複 owner、越界、舊格式均拒絕或重掃。兩表計入 wire `nbytes` 與 resident 成本。建表亦須有上限，不能只限 reader。 |

依據現有 scanner 表格式、transport 長度驗證及 delete 後重掃契約。`model/vector_paths/scan.py:171`、`model/vector_paths/transport.py:151`、`model/vector_paths/transport.py:185`、`model/vector_paths/transport.py:206`、`model/vector_paths/edit.py:6`

G 是參考實作。F 可批次辨認 setter 及 paint，但需依 scope 與事件次序計算**累積交集**；目前「最近一個 clip event」的 bool `sticky()` 無法表示巢狀收窄。兩者使用相同算術次序、取整、rect 編號及拒絕規則。對 F 宣告支援的 fixture 明斷 `scanner == "F"`，逐 byte 比舊表、新表及 flags；強制小批次、跨 stream、scope 邊界。另測合法 fallback 與相同拒絕理由，避免 F 一律退 G 仍得綠燈。`model/vector_paths/scan_fast.py:710`、`model/vector_paths/scan_fast.py:803`、`test_scripts/test_vector_scan_fast.py:28`、`test_scripts/test_vector_scan_fast.py:51`

### 5. 獨立像素 oracle 與失敗判定

- **正控制。** 手寫四份 fixture，交叉組合「原位／已知安全目的地」與「有／無目標 clip」。目的地直接寫出預期座標；背景、裁切以外的鄰物、重疊物及順序一致。先確認目標確實有墨且移位前後可區分；同位置兩版於 1×／2×／4× 整頁逐像素相等。正式 move 的結果另與獨立目的地比對，儲存重開後再比，檢查 setter、鄰物及未選列沒有移動。fixture 選用可精確表示的位移。`plans/b7-clipped-design-draft.md:24`、`plans/cad-vector-object-editing.md:299`
- **負控制。** 目的地越界、寬筆中心線在內而帽端在外、尖 miter、帶洞 `W*`、巢狀窄 clip 各安排可見墨跡被切掉的位置，先證明移除 clip 會產生像素差，再要求 preflight 拒絕且零寫入。另測恰貼邊、相差一個可表示值、微 shear、未知 `gs`、hairline、text clip；這些案例驗保守拒絕，毋須硬造像素差。加 `Q` 後兄弟列可移動、負尺寸、反射、旋轉、CropBox 偏移與 `/UserUnit`。`plans/b7-design-astra.md:79`、`plans/cad-vector-object-editing.md:292`
- **選取／刪除回歸。** 維持依 constructed geometry 查詢，遮住的路段仍可選整個 parent；setter 不可刪。刪除後與獨立 survivor-only 文件比較。三種解析度的像素相等是對實作的反證手段；任意目的地的安全性仍由幾何證據決定。`test_scripts/test_vector_index_queries.py:282`、`model/vector_paths/edit.py:3`

### 6. 紅燈實作順序

1. **語料盤點** — 在 `plans/b7-clipped-design-draft.md` 記錄上述逐頁漏斗與代表 row；以 `test_scripts/test_vector_scan.py` 的合成頁校準原因分類。先決定是否有實際移動增益。
2. **狀態與時序** — 在 `test_scripts/test_vector_scan.py` 先使合法內含列失敗，並固定 setter、`W n`、text clip、巢狀交集、跨 stream、`Q` 兄弟的預期，再改 `model/vector_paths/scan.py`。
3. **墨跡與證據** — 同檔先讓寬筆、miter、曲線、貼邊及未知筆寬反例失敗，再實作界限與稀疏表；在 `test_scripts/test_vector_movable_subset.py` 驗其他 blocker 與 mixed selection。
4. **F parity** — `test_scripts/test_vector_scan_fast.py` 先要求真 F 產生與 G 完全相同的證據，再改 `model/vector_paths/scan_fast.py`。
5. **傳輸與安裝** — `test_scripts/test_vector_scan_child.py` 先測 round-trip、截斷、缺證、錯 owner、重複與超額，再改 `model/vector_paths/transport.py`、`model/pdf_model.py`；確認失敗不發布 index。
6. **目的地與不可部分寫入** — 在規劃中的 `test_scripts/test_vector_move_model.py` 先測可表示安全位移、序列化後貼邊、混選一列越界、stale token；再接 `model/vector_paths/edit.py` 與 Model preflight。通過這步才讓產品宣告裁切列可移動。既有 move 規劃位置見 `plans/cad-vector-object-editing.md:401`。
7. **外觀與產品入口** — 用 `test_scripts/vector_fixture_builder.py` 建獨立預期，擴充 `test_scripts/test_vector_index_queries.py`、`test_scripts/test_vector_oracle_saved.py` 與正式 move 流程的 save/reopen 比對。最後才重測 CAD 記憶體、冷／暖查詢及 GUI；分開報幾何、像素與延遲結果。

## Evidence

- `git status --short --branch --untracked-files=all`、`git rev-parse --short HEAD` → exit 0；審查基準為 `feat/true-text-edge-cases`、HEAD `4f608d04`，含未追蹤 B7 程式、測試及草稿。
- `git diff`、`git diff --check` → exit 0。審查期間工作樹另出現 `TODOS.md`、`docs/ARCHITECTURE.md` 變更，已讀入。進度檔中的 mypy 舊輸出與現行兩處原始碼不一致，不能當作本版結果。`plans/b7-progress.md:24`、`model/pdf_model.py:668`、`model/pdf_model.py:4539`

**Not performed**　依要求未執行 pytest、Qt、benchmark、計時或像素渲染；未宣告正在執行的全套測試通過。

**Fence log**　全程唯讀，未編輯檔案。採本輪 Plan A 的 Undo 語意；另一份 OCR 跨 Undo 保存提案仍列為待裁決。`TODOS.md:4`

**Verified**　沿 `commit_delete → None → write_transaction`、`jump_to_result → get_page_pixmap`、換裝 index 後直接讀 `vector_selection_segments` 三條路徑反查，均找到仍可達的缺口；沿 `activate → connect_bridge → on_ocr_applied` 則確認正式接線已補上。

## Part A　Must-fix（依序）

1. 明確區分 publish、已驗證 rollback、damaged；在同一 lease 內完成 after-capture、history 與失敗處置。每次 H22 yield 返回重驗 session／handle／revision，T1 發現外部變更時保留現場。
2. 封住關窗、CLI、真實導航／render、timer 與直接 Model／tool 入口；傳遞合法巢狀 lease，覆蓋向量 Undo／Redo。用上述類別層級測試找出遺漏。
3. OCR 綁定辨識快照，去重且依序逐頁確認；處理部分寫入、dirty 與單次通知。damaged session 不得自動 drain。
4. 所有 selection 消費端統一驗身分；封住舊 mask 外洩，讓已發布 index 與 query cache 有可強制的不可變契約。
5. 接上互動刪除前，修正退化 subpath、白底誤選、`gs` 的 `/LC`／`/LW` 與 sparse ordinal 驗證；錯誤命中會把另一個 parent 送入 delete。`model/vector_paths/scan.py:962`、`model/vector_paths/scan_fast.py:1235`、`model/vector_paths/transport.py:253`、`plans/b7-review-r1.md:23`

## Part A　Should-fix（依序）

1. 將 query resident bytes 納入淘汰，記錄安裝峰值；重測冷／暖、零點／稀疏／密集點及 countable fall-through 的**單次最大值**，再判定 50 ms gate。
2. 補 `all/clear/add/toggle` 的 token 對照、等長及不同長度 index 的舊 accessor、真實 OCR bridge、非例外 commit 失敗與 history trim 故障測例。
3. 更新進度檔中「DONE」、歷史 mypy 輸出與 review 檔名，清楚區分已接線、已有測例、已經產品入口驗收三種狀態。