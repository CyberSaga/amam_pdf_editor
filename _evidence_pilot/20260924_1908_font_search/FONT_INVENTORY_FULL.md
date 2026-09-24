# FONT_INVENTORY_FULL — 20260924_1908 (Asia/Taipei)

Search-only inventory. **No PDF mutations. No product source changes. No case_ids invented.**

## Scope
- Deep-scanned PDFs: **49** (`test_files/*.pdf` + `sample-files-main` + `Test-PDF-Files-master`)
- veraPDF corpus: **2887** total; light font-name scan **499** files
- Method: PyMuPDF `get_fonts(full=True)` + `get_texttrace()` for actual shows; xref parse for Subtype/Encoding/ToUnicode/embedded
- Stream seq fingerprints via project `shows()` where available (see FINGERPRINTS.json)

## Known already (not rediscovered as new)
- HVAC: PMingLiU, ArialMT, MicrosoftJhengHeiRegular — piloted
- ECC: DFKaiShu-SB-Estd-BF — piloted ecc-1/2/3
- ECC MicrosoftJhengHeiRegular — present, **no** documented edit seq → listed as candidate
- CHB + [AIRPORT_CODE] — vector only
- 01_報告 DFKaiShu — present, **no** case_id → listed as candidate

## Vector-only PDFs (NOT true-text pilotable)
- `[VECTOR_CHB_PDF]` sha256=`1580cbc98bc4506d6c8ea73b732eb91267468f4311a4ed21e943ac4f89c2024d` — font_resources empty; outline lettering
- `[VECTOR_AIRPORT_PDF]` sha256=`c994e9f888588a6684cd64bdff8e4b0ea6c85fc46eed3b4d0c8cd8120c0494f7` — font_resources empty; outline lettering

## Per-PDF inventory (deep scan)

### 01_報告書.pdf
- path: `test_files/01_報告書.pdf`
- sha256: `880a637fe94734411fda89043e7abbe060b938b7a6dd09c04292bca19f8b320f`
- pages: 23 | text_class: **true_text** | approx_shows: 2378

| BaseFont (clean) | Subtype | Encoding | emb | TU | shows | class | sample |
|---|---|---|---|---|---:|---|---|
| DFKaiShu-SB-Estd-BF | Type0 | Identity-H | True | True | 2265 | nondefault_cjk_kai | 11; 4 |
| TimesNewRomanPSMT | TrueType | WinAnsiEncoding | True | False | 52 | defaultish | (; ) |
| ArialNarrow | TrueType | WinAnsiEncoding | True | False | 26 | defaultish | (; ) |
| ArialMT | TrueType | WinAnsiEncoding | True | False | 10 | defaultish |  |
| TimesNewRomanPS-BoldMT | TrueType | WinAnsiEncoding | True | False | 10 | defaultish | (; ) |
| Arial-BoldMT | TrueType | WinAnsiEncoding | True | False | 8 | defaultish |  |
| MingLiU | TrueType | WinAnsiEncoding | True | False | 7 | defaultish | 1 |

### 1.pdf
- path: `test_files/1.pdf`
- sha256: `00f70888def599dd8da3fc2466222fdec47df44c69c6cfcf2af2153f41cc4eab`
- pages: 1 | text_class: **true_text** | approx_shows: 26

| BaseFont (clean) | Subtype | Encoding | emb | TU | shows | class | sample |
|---|---|---|---|---|---:|---|---|
| Helvetica | Type1 | WinAnsiEncoding | True | False | 26 | defaultish | When; I |

### Awareness.pdf
- path: `test_files/Awareness.pdf`
- sha256: `2cdee708c3a8ff01b3e7e7ebad500323a879f3a9d82ac369fcf6b87094564347`
- pages: 1 | text_class: **true_text** | approx_shows: 29

| BaseFont (clean) | Subtype | Encoding | emb | TU | shows | class | sample |
|---|---|---|---|---|---:|---|---|
| Europa-Regular | Type1 | xref:14 | True | True | 13 | specialty_latin | 10; TRICITYVOICE.COM |
| Europa-Bold | Type1 | xref:24 | True | True | 6 | specialty_latin | By Charlene Dizon; STANFORD RAISES ALCOHOL INTOLERANCE AW... |
| Canela-Medium | Type1 | xref:19 | True | True | 3 | specialty_latin | HEALTH; & |
| IvyPrestoText-Light | Type1 | xref:34 | True | True | 3 | specialty_latin | lcohol is a normalized part of socializing, from grabbing... |
| ACaslonPro-Regular | Type1 | xref:39 | True | True | 2 | specialty_latin | ‘; ’ |
| Canela-Bold | Type1 | xref:29 | True | True | 1 | specialty_latin | A |
| IvyPrestoText-LightItali | Type1 | xref:34 | True | True | 1 | specialty_latin | To learn more about AICAP,  please visit aicap24.org. |

### [VECTOR_CHB_PDF]
- path: `test_files/[VECTOR_CHB_PDF]`
- sha256: `1580cbc98bc4506d6c8ea73b732eb91267468f4311a4ed21e943ac4f89c2024d`
- pages: 1 | text_class: **vector_outline** | approx_shows: 0
- fonts_from_shows: _(none — vector outline)_

### [ECC_DWG].pdf
- path: `test_files/[ECC_DWG].pdf`
- sha256: `0f75dd10ed77214c5cf159d40f909cd402231761886cb0ed3821368ac0ab1853`
- pages: 1 | text_class: **true_text** | approx_shows: 62

| BaseFont (clean) | Subtype | Encoding | emb | TU | shows | class | sample |
|---|---|---|---|---|---:|---|---|
| DFKaiShu-SB-Estd-BF | Type0 | Identity-H | True | True | 32 | nondefault_cjk_kai | 台灣電力; 股份有限公司 |
| MicrosoftJhengHeiRegular | Type0 | Identity-H | True | True | 30 | specialty_other | 排煙室; (裝卸平台) |

### [HVAC_DWG_PDF]
- path: `test_files/[HVAC_DWG_PDF]`
- sha256: `9da93de982145c46af0d34a978b4bbaa1167f0937327dedb44ecad4d50fca0a2`
- pages: 50 | text_class: **true_text** | approx_shows: 1017

| BaseFont (clean) | Subtype | Encoding | emb | TU | shows | class | sample |
|---|---|---|---|---|---:|---|---|
| MicrosoftJhengHeiRegular | CIDFontType2 | Identity-H | True | True | 324 | specialty_other | TWX-AC-0-01; 空調系統封面 |
| ArialMT | CIDFontType2 | Identity-H | True | True | 247 | specialty_other | MIC; - |
| PMingLiU | CIDFontType2 | Identity-H | True | True | 163 | specialty_other | 。; NOTES |
| DFKaiShu-SB-Estd-BF | CIDFontType2 | Identity-H | True | True | 112 | nondefault_cjk_kai | [CLIENT_ORG]; [SITE_NAME] |
| TimesNewRomanPSMT | Type0 | Identity-H | True | True | 107 | defaultish | [CLIENT_ACRONYM]; MIC |
| Arial-BoldMT | CIDFontType2 | Identity-H | True | True | 29 | specialty_other | Title; Doc. No. |
| SimSun | CIDFontType2 | Identity-H | True | True | 15 | nondefault_cjk_song | I; 1F2F-平台 |
| TrebuchetMS | CIDFontType2 | Identity-H | True | True | 9 | specialty_latin | M5 System Engineering Division |
| TimesNewRomanPS-BoldMT | TrueType | WinAnsiEncoding | True | False | 8 | defaultish | [CLIENT_ACRONYM]; - |
| MicrosoftJhengHeiBold | Type0 | Identity-H | True | True | 2 | specialty_other | [SITE_SHORT]; 建置工程 |
| MicrosoftYaHei-Bold | CIDFontType2 | Identity-H | True | True | 1 | nondefault_cjk_yahei | 空調系統 |

### test-colored-background.pdf
- path: `test_files/test-colored-background.pdf`
- sha256: `00640a01cecf0bfdf58bf72d6cbd20957ef98dcfc87b32f7f8b9e4a42eb36dba`
- pages: 8 | text_class: **true_text** | approx_shows: 104

| BaseFont (clean) | Subtype | Encoding | emb | TU | shows | class | sample |
|---|---|---|---|---|---:|---|---|
| 1 | TrueType | WinAnsiEncoding | True | False | 94 | other_named | Revit Pre; - |
| 2,Bold | Type0 | Identity-H | True | True | 9 | other_named | Revit; 前置作業操作流程 |
| Helvetica | None | None | None | None | 1 | defaultish | 222uiii |

### test-complexed-layout.pdf
- path: `test_files/test-complexed-layout.pdf`
- sha256: `faefb744200aad617504802b72fd20c7525bab203f849f22a38af07f127bedf3`
- pages: 2 | text_class: **true_text** | approx_shows: 1518

| BaseFont (clean) | Subtype | Encoding | emb | TU | shows | class | sample |
|---|---|---|---|---|---:|---|---|
| Consolas | Type0/CIDFontType2 | Identity-H | True | True | 379 | specialty_latin | cursor; : |
| Type3 (8 0 R) | None | None | None | None | 98 | specialty_other | ⽂; 時 |
| Consolas-Italic | Type0/CIDFontType2 | Identity-H | True | True | 97 | specialty_latin | 1370; 1371 |
| Type3 (9 0 R) | None | None | None | None | 61 | specialty_other | 字; 容 |
| Type3 (28 0 R) | None | None | None | None | 46 | specialty_other | ，; 。 |
| Type3 (14 0 R) | None | None | None | None | 45 | specialty_other | 的; 直 |
| Type3 (13 0 R) | None | None | None | None | 37 | specialty_other | 有; 會 |
| Type3 (37 0 R) | None | None | None | None | 37 | specialty_other | 來; 以 |
| Type3 (22 0 R) | None | None | None | None | 31 | specialty_other | 到; 先 |
| Type3 (26 0 R) | None | None | None | None | 31 | specialty_other | Stirling-PDF; X |
| Type3 (19 0 R) | None | None | None | None | 24 | specialty_other | 不; 中 |
| Type3 (29 0 R) | None | None | None | None | 22 | specialty_other | 透過; 邏 |
| Type3 (6 0 R) | None | None | None | None | 21 | specialty_other | 編; 繁 |
| Type3 (11 0 R) | None | None | None | None | 21 | specialty_other | 除; 關 |
| Type3 (23 0 R) | None | None | None | None | 21 | specialty_other | 原; 取 |
| Type3 (33 0 R) | None | None | None | None | 21 | specialty_other | 右; 否 |
| Type3 (56 0 R) | None | None | None | None | 20 | specialty_other | 系統; 素 |
| Type3 (5 0 R) | None | None | None | None | 19 | specialty_other | 在; 圖 |
| Type3 (15 0 R) | None | None | None | None | 19 | specialty_other | 做; 個 |
| Type3 (39 0 R) | None | None | None | None | 19 | specialty_other | 現; 獲 |
| Type3 (34 0 R) | None | None | None | None | 18 | specialty_other | ⾓; 設 |
| Type3 (18 0 R) | None | None | None | None | 17 | specialty_other | 增; 執 |
| Type3 (21 0 R) | None | None | None | None | 17 | specialty_other | 響; 預 |
| IBMPlexMono-Regular | Type0/CIDFontType2 | Identity-H | True | True | 15 | specialty_latin | PdfTextEditorView.tsx:1373-1395; PdfTextEditorView.tsx:13... |
| Type3 (58 0 R) | None | None | None | None | 14 | specialty_other | ：; （ |
| Type3 (66 0 R) | None | None | None | None | 14 | specialty_other | 空; 移 |
| ArialUnicodeMS | Type0/CIDFontType2 | Identity-H | True | True | 14 | specialty_other | 绝访问; 没 |
| Type3 (7 0 R) | None | None | None | None | 13 | specialty_other | 輯; 輸 |
| Type3 (43 0 R) | None | None | None | None | 13 | specialty_other | ⽂; 是 |
| Type3 (38 0 R) | None | None | None | None | 12 | specialty_other | 實; 對 |
| Type3 (86 0 R) | None | None | None | None | 12 | specialty_other | 翻; 群 |
| Type3 (31 0 R) | None | None | None | None | 11 | specialty_other | 擊; 操 |
| Type3 (10 0 R) | None | None | None | None | 10 | specialty_other | 清; 活 |
| Type3 (12 0 R) | None | None | None | None | 10 | specialty_other | 舊; 能 |
| Type3 (55 0 R) | None | None | None | None | 10 | specialty_other | ⼾; 態 |
| Type3 (64 0 R) | None | None | None | None | 10 | specialty_other | 檢; 步 |
| Type3 (98 0 R) | None | None | None | None | 10 | specialty_other | Stirling-Tools/Stirling-PDF; frontend/src/core/components... |
| Type3 (32 0 R) | None | None | None | None | 9 | specialty_other | 框; 查 |
| Type3 (78 0 R) | None | None | None | None | 9 | specialty_other | 狀; ⽚ |
| Type3 (16 0 R) | None | None | None | None | 8 | specialty_other | 法; 況 |
| Type3 (20 0 R) | None | None | None | None | 8 | specialty_other | 影; 強 |
| Type3 (35 0 R) | None | None | None | None | 8 | specialty_other | 按; 接 |
| Type3 (44 0 R) | None | None | None | None | 8 | specialty_other | 字 |
| Type3 (54 0 R) | None | None | None | None | 8 | specialty_other | 當; ⽤ |
| Type3 (57 0 R) | None | None | None | None | 8 | specialty_other | ⾏ |
| Type3 (65 0 R) | None | None | None | None | 7 | specialty_other | 為; 然 |
| Type3 (85 0 R) | None | None | None | None | 7 | specialty_other | 管; 範 |
| Type3 (62 0 R) | None | None | None | None | 6 | specialty_other | 空; 種 |
| Type3 (84 0 R) | None | None | None | None | 6 | specialty_other | 部; 都 |
| Type3 (138 0 R) | None | None | None | None | 6 | specialty_other | 性; 意 |
| Type3 (27 0 R) | None | None | None | None | 5 | specialty_other | 器 |
| Type3 (30 0 R) | None | None | None | None | 5 | specialty_other | 點 |
| Type3 (47 0 R) | None | None | None | None | 5 | specialty_other | 作; 事件 |
| Type3 (82 0 R) | None | None | None | None | 5 | specialty_other | ⽰; 確 |
| Type3 (87 0 R) | None | None | None | None | 5 | specialty_other | 譯; 變 |
| Type3 (73 0 R) | None | None | None | None | 4 | specialty_other | 理; 獨 |
| Type3 (130 0 R) | None | None | None | None | 4 | specialty_other | ⾴; ⾯ |
| Type3 (42 0 R) | None | None | None | None | 3 | specialty_other | 除; 隔 |
| Type3 (48 0 R) | None | None | None | None | 3 | specialty_other | 機; 檢 |
| Type3 (49 0 R) | None | None | None | None | 3 | specialty_other | 制; 兩 |
| Type3 (50 0 R) | None | None | None | None | 3 | specialty_other | 主; 不 |
| Type3 (61 0 R) | None | None | None | None | 3 | specialty_other | 為 |
| Type3 (63 0 R) | None | None | None | None | 3 | specialty_other | ⾸; 顯 |
| Type3 (69 0 R) | None | None | None | None | 3 | specialty_other | 果; 有 |
| Type3 (77 0 R) | None | None | None | None | 3 | specialty_other | 驟; 體 |
| Type3 (80 0 R) | None | None | None | None | 3 | specialty_other | 反; 原 |
| Type3 (89 0 R) | None | None | None | None | 3 | specialty_other | 如 |
| SegoeFluentIcons | Type0/CIDFontType2 | Identity-H | True | True | 3 | specialty_other | ;  |
| Type3 (4 0 R) | None | None | None | None | 2 | specialty_other | Stirling-Tools/Stirling-PDF |
| Type3 (17 0 R) | None | None | None | None | 2 | specialty_other | Fast |
| Type3 (36 0 R) | None | None | None | None | 2 | specialty_other | 鈕 |
| Type3 (41 0 R) | None | None | None | None | 2 | specialty_other | 清 |
| Type3 (45 0 R) | None | None | None | None | 2 | specialty_other | 的 |
| Type3 (51 0 R) | None | None | None | None | 2 | specialty_other | 要; 設計 |
| Type3 (52 0 R) | None | None | None | None | 2 | specialty_other | 邏; 運 |
| Type3 (68 0 R) | None | None | None | None | 2 | specialty_other | 如 |
| Type3 (71 0 R) | None | None | None | None | 2 | specialty_other | 經; 組 |
| Type3 (75 0 R) | None | None | None | None | 2 | specialty_other | 處 |
| Type3 (83 0 R) | None | None | None | None | 2 | specialty_other | Notes |
| Type3 (88 0 R) | None | None | None | None | 2 | specialty_other | 標; 構 |
| Type3 (90 0 R) | None | None | None | None | 2 | specialty_other | 「; 」 |
| Type3 (96 0 R) | None | None | None | None | 2 | specialty_other | ❌ |
| Type3 (125 0 R) | None | None | None | None | 2 | specialty_other | 群; 者 |
| Type3 (127 0 R) | None | None | None | None | 2 | specialty_other | 保 |
| Type3 (129 0 R) | None | None | None | None | 2 | specialty_other | 變; 護 |
| Type3 (136 0 R) | None | None | None | None | 2 | specialty_other | 已 |
| Type3 (139 0 R) | None | None | None | None | 2 | specialty_other | ⾊ |
| Type3 (24 0 R) | None | None | None | None | 1 | specialty_other | View as codemap |
| Type3 (46 0 R) | None | None | None | None | 1 | specialty_other | 實 |
| Type3 (53 0 R) | None | None | None | None | 1 | specialty_other | 輯 |
| Type3 (59 0 R) | None | None | None | None | 1 | specialty_other | 查 |
| Type3 (60 0 R) | None | None | None | None | 1 | specialty_other | 否 |
| Type3 (67 0 R) | None | None | None | None | 1 | specialty_other | 式 |
| Type3 (70 0 R) | None | None | None | None | 1 | specialty_other | 已 |
| Type3 (72 0 R) | None | None | None | None | 1 | specialty_other | 處 |
| Consolas-Bold | Type0/CIDFontType2 | Identity-H | True | True | 1 | specialty_latin | onMouseDown |
| Type3 (76 0 R) | None | None | None | None | 1 | specialty_other | 鍵 |
| Type3 (79 0 R) | None | None | None | None | 1 | specialty_other | UI |
| Type3 (81 0 R) | None | None | None | None | 1 | specialty_other | 饋 |
| Type3 (108 0 R) | None | None | None | None | 1 | specialty_other | DeepWiki |
| Type3 (109 0 R) | None | None | None | None | 1 | specialty_other | Devin |
| Type3 (110 0 R) | None | None | None | None | 1 | specialty_other | Share |
| Type3 (111 0 R) | None | None | None | None | 1 | specialty_other | Index your code with |
| Type3 (123 0 R) | None | None | None | None | 1 | specialty_other | 增 |
| Type3 (124 0 R) | None | None | None | None | 1 | specialty_other | 性 |
| Type3 (126 0 R) | None | None | None | None | 1 | specialty_other | 管 |
| Type3 (128 0 R) | None | None | None | None | 1 | specialty_other | 持 |
| Type3 (131 0 R) | None | None | None | None | 1 | specialty_other | 狀 |
| Type3 (132 0 R) | None | None | None | None | 1 | specialty_other | 態 |
| Type3 (133 0 R) | None | None | None | None | 1 | specialty_other | ⾃ |
| Type3 (134 0 R) | None | None | None | None | 1 | specialty_other | 縮 |
| Type3 (135 0 R) | None | None | None | None | 1 | specialty_other | 跳 |
| Type3 (137 0 R) | None | None | None | None | 1 | specialty_other | ⽤ |
| Type3 (140 0 R) | None | None | None | None | 1 | specialty_other | 拒 |

### test-hierarchy-bookmarks.pdf
- path: `test_files/test-hierarchy-bookmarks.pdf`
- sha256: `f93ba509283b805c629a48d2adc0b3a3a21412b8437fde1de28a5ae773fa5a78`
- pages: 3 | text_class: **true_text** | approx_shows: 1438

| BaseFont (clean) | Subtype | Encoding | emb | TU | shows | class | sample |
|---|---|---|---|---|---:|---|---|
| ArialMT | Type0/CIDFontType2 | Identity-H | True | True | 1176 | specialty_other | Repo; status |
| RobotoMono-Regular | Type0/CIDFontType2 | Identity-H | True | True | 140 | specialty_other | plans/; plans/milestone-2-bugs-security.md |
| Arial-BoldMT | Type0/CIDFontType2 | Identity-H | True | True | 84 | specialty_other | Milestone; 2 |
| Arial-ItalicMT | Type0/CIDFontType2 | Identity-H | True | True | 33 | specialty_other | "PLANNING; APPROVED |
| MS-Gothic | Type0/CIDFontType2 | Identity-H | True | True | 4 | nondefault_cjk_hei_other | 無; 效 |
| RobotoMono-Bold | Type0/CIDFontType2 | Identity-H | True | True | 1 | specialty_other | get_page_label |

### test-horizontal-texts.pdf
- path: `test_files/test-horizontal-texts.pdf`
- sha256: `e1c4920a310de4c894b70b037b6f935668405f41858800419c541c9e0028e3c4`
- pages: 1 | text_class: **true_text** | approx_shows: 30

| BaseFont (clean) | Subtype | Encoding | emb | TU | shows | class | sample |
|---|---|---|---|---|---:|---|---|
| Aptos | Type0 | Identity-H | True | True | 17 | specialty_latin | program; testrunning |
| PMingLiU | CIDFontType2 | Identity-H | True | True | 13 | specialty_other | 測試參考; wh |

### test-large-file.damaged.pdf
- path: `test_files/test-large-file.damaged.pdf`
- sha256: `43832f30b0f3deb6c82d0c00a3b4c5e0816f1cf789d376c27a174798c8d491fa`
- pages: 402 | text_class: **true_text** | approx_shows: 1907

| BaseFont (clean) | Subtype | Encoding | emb | TU | shows | class | sample |
|---|---|---|---|---|---:|---|---|
| Arial,Bold | TrueType | WinAnsiEncoding | True | False | 888 | defaultish | Click to BUY NOW!; P |
| ArialMT | Type0/CIDFontType2 | Identity-H | True | True | 877 | specialty_other | ANSI/TIA-942-B-2017 APPROVED: JULY 12, 2017; TIA Engineer... |
| Arial-BoldMT | Type0/CIDFontType2 | Identity-H | True | True | 80 | specialty_other | TIA-942-B  (Revision of TIA-942-A)  July 2017; Telecommun... |
| Calibri | Type0/CIDFontType2 | Identity-H | True | True | 42 | specialty_other |  |
| Cambria | Type0/CIDFontType2 | Identity-H | True | True | 7 | specialty_other | ) |
| Courier | Type1 | WinAnsiEncoding | True | False | 7 | defaultish | ```, |
| TimesNewRomanPSMT | Type0/CIDFontType2 | Identity-H | True | True | 3 | specialty_other |  |
| Arial-ItalicMT | TrueType | WinAnsiEncoding | True | False | 1 | defaultish | <T»> |
| Arial-BoldItalicMT | TrueType | WinAnsiEncoding | True | False | 1 | defaultish | ANSI |
| SymbolMT | Type0/CIDFontType2 | Identity-H | True | True | 1 | specialty_symbol |  |

### test-large-file.pdf
- path: `test_files/test-large-file.pdf`
- sha256: `a385b8615355690a1279e27a246eb374e3b47564af82bb3ecd96907ddb9fc3cd`
- pages: 402 | text_class: **true_text** | approx_shows: 1907

| BaseFont (clean) | Subtype | Encoding | emb | TU | shows | class | sample |
|---|---|---|---|---|---:|---|---|
| Arial,Bold | TrueType | WinAnsiEncoding | True | False | 888 | defaultish | Click to BUY NOW!; P |
| ArialMT | Type0/CIDFontType2 | Identity-H | True | True | 877 | specialty_other | ANSI/TIA-942-B-2017 APPROVED: JULY 12, 2017; TIA Engineer... |
| Arial-BoldMT | Type0/CIDFontType2 | Identity-H | True | True | 80 | specialty_other | TIA-942-B  (Revision of TIA-942-A)  July 2017; Telecommun... |
| Calibri | Type0/CIDFontType2 | Identity-H | True | True | 42 | specialty_other |  |
| Cambria | Type0/CIDFontType2 | Identity-H | True | True | 7 | specialty_other | ) |
| Courier | Type1 | WinAnsiEncoding | True | False | 7 | defaultish | ```, |
| TimesNewRomanPSMT | Type0/CIDFontType2 | Identity-H | True | True | 3 | specialty_other |  |
| Arial-ItalicMT | TrueType | WinAnsiEncoding | True | False | 1 | defaultish | <T»> |
| Arial-BoldItalicMT | TrueType | WinAnsiEncoding | True | False | 1 | defaultish | ANSI |
| SymbolMT | Type0/CIDFontType2 | Identity-H | True | True | 1 | specialty_symbol |  |

### test-vertical-texts.pdf
- path: `test_files/test-vertical-texts.pdf`
- sha256: `3b0480373461cefa9329c2bccc92c45a83e043b027bedd1a22269aedc2123832`
- pages: 1 | text_class: **true_text** | approx_shows: 28

| BaseFont (clean) | Subtype | Encoding | emb | TU | shows | class | sample |
|---|---|---|---|---|---:|---|---|
| Aptos | TrueType | WinAnsiEncoding | True | False | 28 | specialty_latin | wh; en |

### [VECTOR_AIRPORT_PDF]
- path: `test_files/[VECTOR_AIRPORT_PDF]`
- sha256: `c994e9f888588a6684cd64bdff8e4b0ea6c85fc46eed3b4d0c8cd8120c0494f7`
- pages: 1 | text_class: **vector_outline** | approx_shows: 0
- fonts_from_shows: _(none — vector outline)_

### minimal-document.pdf
- path: `test_files/sample-files-main/001-trivial/minimal-document.pdf`
- sha256: `f723638db6e763cf4ccadad38a3d38a02d9ecab95dab1f0bbf00e801991b5f92`
- pages: 1 | text_class: **true_text** | approx_shows: 1

| BaseFont (clean) | Subtype | Encoding | emb | TU | shows | class | sample |
|---|---|---|---|---|---:|---|---|
| CMR10 | Type1 |  | True | True | 1 | other_named | Loremipsumdolorsitamet,consetetursadipscingelitr,seddiamn... |

### 002-trivial-libre-office-writer.pdf
- path: `test_files/sample-files-main/002-trivial-libre-office-writer/002-trivial-libre-office-writer.pdf`
- sha256: `fc67ce4f76ffb44e818ebe4f673dbeb6002ad93a59f3856ff14fb1d3625f10a5`
- pages: 1 | text_class: **true_text** | approx_shows: 7

| BaseFont (clean) | Subtype | Encoding | emb | TU | shows | class | sample |
|---|---|---|---|---|---:|---|---|
| DejaVuSans | TrueType |  | True | True | 7 | other_named | Lorem ipsum dolor sit amet, consetetur sadipscing elitr, ... |

### pdflatex-image.pdf
- path: `test_files/sample-files-main/003-pdflatex-image/pdflatex-image.pdf`
- sha256: `64c5bc35008015936ef3ff60f6ad268a713b5271727b72ef308f87b9b495646f`
- pages: 1 | text_class: **true_text** | approx_shows: 3

| BaseFont (clean) | Subtype | Encoding | emb | TU | shows | class | sample |
|---|---|---|---|---|---:|---|---|
| CMR10 | Type1 |  | True | True | 2 | other_named | Loremipsumdolorsitamet,consetetursadipscingelitr,seddiamn... |
| CMSSBX10 | Type1 |  | True | True | 1 | other_named | 1YourChapter |

### pdflatex-4-pages.pdf
- path: `test_files/sample-files-main/004-pdflatex-4-pages/pdflatex-4-pages.pdf`
- sha256: `f17a09190ad8a04964d78115d8ba7fc7a298557274fa14932ba58612342b7dec`
- pages: 4 | text_class: **true_text** | approx_shows: 4

| BaseFont (clean) | Subtype | Encoding | emb | TU | shows | class | sample |
|---|---|---|---|---|---:|---|---|
| CMR10 | Type1 |  | True | True | 4 | other_named | Hello,hereissometextwithoutameaning.Thistextshouldshowwha... |

### libreoffice-writer-password.pdf
- path: `test_files/sample-files-main/005-libreoffice-writer-password/libreoffice-writer-password.pdf`
- sha256: `3e333bff0196d0c5320f40cdd1b7a3abd21b316de79de3c0f9083accdaef9358`
- pages: 1 | text_class: **unknown** | approx_shows: 0
- error: `scan:document closed or encrypted`
- fonts_from_shows: _(none extractable)_

### pdflatex-outline.pdf
- path: `test_files/sample-files-main/006-pdflatex-outline/pdflatex-outline.pdf`
- sha256: `17b5a4dac75613b82749c7538fc93991a385a5d419cc9832fdba24c1726a031a`
- pages: 4 | text_class: **true_text** | approx_shows: 23

| BaseFont (clean) | Subtype | Encoding | emb | TU | shows | class | sample |
|---|---|---|---|---|---:|---|---|
| CMR10 | Type1 |  | True | True | 12 | other_named | 1; Hello,hereissometextwithoutameaning.Thistextshouldshow... |
| CMBX12 | Type1 |  | True | True | 10 | other_named | Contents; 1Foo |
| CMBX10 | Type1 |  | True | True | 1 | other_named | 1Foo22Bar23Baz24Foo25Bar36Baz37Foo38Bar49Baz4 |

### imagemagick-ASCII85Decode.pdf
- path: `test_files/sample-files-main/007-imagemagick-images/imagemagick-ASCII85Decode.pdf`
- sha256: `99c687865a8c81b11fe2b6be84b4aaf47bf785556d07274debf9bc1e0807ed2f`
- pages: 1 | text_class: **unknown_or_empty** | approx_shows: 0
- fonts_from_shows: _(none extractable)_

### imagemagick-CCITTFaxDecode.pdf
- path: `test_files/sample-files-main/007-imagemagick-images/imagemagick-CCITTFaxDecode.pdf`
- sha256: `cf6f94b533dc28974961fd62a67ebfc722224a0be8a4f0c4c91b26a522d5f70d`
- pages: 1 | text_class: **unknown_or_empty** | approx_shows: 0
- fonts_from_shows: _(none extractable)_

### imagemagick-images.pdf
- path: `test_files/sample-files-main/007-imagemagick-images/imagemagick-images.pdf`
- sha256: `0f2076573bfed1107300a2383b88bbbbc2b85a57f06b3ff478a0faa7ded57b4e`
- pages: 6 | text_class: **true_text** | approx_shows: 4

| BaseFont (clean) | Subtype | Encoding | emb | TU | shows | class | sample |
|---|---|---|---|---|---:|---|---|
| Helvetica | Type1 | MacRomanEncoding | True | False | 4 | defaultish | Background |

### imagemagick-lzw.pdf
- path: `test_files/sample-files-main/007-imagemagick-images/imagemagick-lzw.pdf`
- sha256: `ee7ce5f301920761371b0a2537634c39b9a8cd2ab578dee4c17056da297628d8`
- pages: 1 | text_class: **unknown_or_empty** | approx_shows: 0
- fonts_from_shows: _(none extractable)_

### inline-image.pdf
- path: `test_files/sample-files-main/008-reportlab-inline-image/inline-image.pdf`
- sha256: `db5c34fea270f38b152d8476e6f3bba855460958e957f69a0542002538cac1c2`
- pages: 1 | text_class: **true_text** | approx_shows: 1

| BaseFont (clean) | Subtype | Encoding | emb | TU | shows | class | sample |
|---|---|---|---|---|---:|---|---|
| Helvetica | Type1 | WinAnsiEncoding | True | False | 1 | defaultish | Test |

### GeoTopo-komprimiert.pdf
- path: `test_files/sample-files-main/009-pdflatex-geotopo/GeoTopo-komprimiert.pdf`
- sha256: `20430e92d42bc06c606f5889d9832c8e5c4dde17f8333f99fbcba96b3a0cba14`
- pages: 117 | text_class: **true_text** | approx_shows: 31164

| BaseFont (clean) | Subtype | Encoding | emb | TU | shows | class | sample |
|---|---|---|---|---|---:|---|---|
| CMMI10 | Type1 | xref:189 | True | False | 8825 | other_named | S; T |
| CMR10 | Type1 | xref:2000 | True | False | 5869 | other_named | (; ) |
| SFRM1095 | Type1 | xref:3610 | True | False | 5844 | other_named | 0.Auﬂage,31.Dezember2016MartinThoma; DiesesSkriptwurdeimW... |
| CMSY10 | Type1 | xref:197 | True | False | 3209 | other_named | ∀; ∃ |
| CMR8 | Type1 | xref:2000 | True | False | 2240 | other_named | 2; 1 |
| CMMI8 | Type1 |  | True | False | 1595 | other_named | i; I |
| CMSY8 | Type1 |  | True | False | 707 | other_named | ∈; ◦ |
| SFBX1095 | Type1 | xref:3610 | True | False | 545 | other_named | Deﬁnition1; topologischerRaum |
| MSBM10 | Type1 |  | True | False | 544 | other_named | R; C |
| CMEX10 | Type1 |  | True | False | 458 | other_named | �; �� |
| CMR6 | Type1 |  | True | False | 191 | other_named | 2; 1 |
| SFRM0900 | Type1 | xref:3610 | True | False | 188 | other_named | (a); (b) |
| EUFM10 | Type1 |  | True | False | 136 | other_named | T; B |
| MSAM10 | Type1 |  | True | False | 131 | other_named | ■; ∠ |
| NimbusSanL-Bold | Type1 | xref:1899 | True | False | 103 | other_named | iii; 2Inhaltsverzeichnis |
| SFRM0800 | Type1 | xref:3610 | True | False | 95 | other_named | A; triv |
| CMMI6 | Type1 |  | True | False | 84 | other_named | U; M |
| CMMI9 | Type1 |  | True | False | 77 | other_named | S; T |
| CMSY6 | Type1 |  | True | False | 46 | other_named | ⊆; − |
| SFSX1095 | Type1 | xref:3610 | True | False | 40 | other_named | 1TopologischeGrundbegriﬀe; 2 |
| SFSX1440 | Type1 | xref:3610 | True | False | 33 | other_named | Danksagungen; WasistTopologie? |
| SFSX1200 | Type1 | xref:3610 | True | False | 32 | other_named | Aufgabe1(Sierpińskiraum); Aufgabe2 |
| CMR9 | Type1 |  | True | False | 31 | other_named | (0); =1 |
| SFTI1095 | Type1 | xref:3610 | True | False | 25 | other_named | Spurtopologie; Unterraumtopologie |
| CMSY9 | Type1 |  | True | False | 19 | other_named | ≥; − |
| Type3 (218 0 R) | None | None | None | None | 19 | specialty_other | bbbb; b |
| SFSX2074 | Type1 | xref:3610 | True | False | 13 | other_named | Vorwort; Inhaltsverzeichnis |
| SFRM0600 | Type1 | xref:3610 | True | False | 12 | other_named | 1; 2 |
| SFTT1095 | Type1 | xref:3610 | True | False | 11 | other_named | commons.wikimedia.org/wiki/File:Blue_Unknot.png; commons.... |
| CMBX10 | Type1 | xref:167 | True | False | 8 | other_named | N; ˆP |
| CMMI12 | Type1 | xref:2000 | True | False | 4 | other_named | ab; s |
| XYATIP-Medium | Type1 |  | True | False | 3 | other_named | � |
| XYBTIP-Medium | Type1 |  | True | False | 3 | other_named | � |
| CMR7 | Type1 | xref:185 | True | False | 3 | other_named | 2; 3 |
| SFBX0800 | Type1 | xref:3610 | True | False | 2 | other_named | 1; 2 |
| LINE10 | Type1 |  | True | False | 2 | other_named | ���;  |
| CMMI7 | Type1 | xref:179 | True | False | 2 | other_named | π |
| CMEX8 | Type1 |  | True | False | 2 | other_named | � |
| CMMIB10 | Type1 |  | True | False | 2 | other_named | π; S |
| CMBX8 | Type1 |  | True | False | 2 | other_named | 1 |
| CMTI8 | Type1 |  | True | False | 2 | other_named | 1; 2 |
| SFBI1095 | Type1 | xref:3610 | True | False | 2 | other_named | G; L |
| SFBX1440 | Type1 | xref:3610 | True | False | 1 | other_named | EinführungindieGeometrieundTopologie |
| CMTI10 | Type1 |  | True | False | 1 | other_named | e |
| SFTT0900 | Type1 | xref:3610 | True | False | 1 | other_named | https://github.com/MartinThoma/LaTeX-examples/tree/master... |
| SFBI0900 | Type1 | xref:3610 | True | False | 1 | other_named | V |
| SFTI0900 | Type1 | xref:3610 | True | False | 1 | other_named | anishingSet |

### GeoTopo.pdf
- path: `test_files/sample-files-main/009-pdflatex-geotopo/GeoTopo.pdf`
- sha256: `a0b9242aef9b5a2c4850160cc9aaf64f5c7b8be705d6872ae28aebf5ab512540`
- pages: 117 | text_class: **true_text** | approx_shows: 6482

| BaseFont (clean) | Subtype | Encoding | emb | TU | shows | class | sample |
|---|---|---|---|---|---:|---|---|
| CMMI10 | Type1 |  | True | False | 1647 | other_named | S; T |
| SFRM1095 | Type1 | xref:3918 | True | False | 1335 | other_named | 0.Auﬂage,31.Dezember2016MartinThoma; DiesesSkriptwurdeimW... |
| CMR10 | Type1 |  | True | False | 995 | other_named | (; ) |
| CMSY10 | Type1 |  | True | False | 805 | other_named | ∀; ∃ |
| CMMI8 | Type1 |  | True | False | 415 | other_named | i; I |
| CMR8 | Type1 |  | True | False | 390 | other_named | 2; 1 |
| MSBM10 | Type1 |  | True | False | 171 | other_named | R; C |
| SFBX1095 | Type1 | xref:3918 | True | False | 148 | other_named | Deﬁnition1; topologischerRaum |
| CMEX10 | Type1 |  | True | False | 127 | other_named | �; �� |
| EUFM10 | Type1 |  | True | False | 105 | other_named | T; B |
| CMSY8 | Type1 |  | True | False | 84 | other_named | ∈; ◦ |
| SFRM0900 | Type1 | xref:3918 | True | False | 43 | other_named | (a); (b) |
| SFRM0800 | Type1 | xref:3918 | True | False | 28 | other_named | A; triv |
| CMMI6 | Type1 |  | True | False | 27 | other_named | U; M |
| NimbusSanL-Bold | Type1 | xref:3951 | True | False | 25 | other_named | iii; 2Inhaltsverzeichnis |
| CMR6 | Type1 |  | True | False | 25 | other_named | 2; 1 |
| SFSX1095 | Type1 | xref:3918 | True | False | 22 | other_named | 1TopologischeGrundbegriﬀe; 2 |
| MSAM10 | Type1 |  | True | False | 19 | other_named | ■ |
| CMMI9 | Type1 |  | True | False | 12 | other_named | S; T |
| SFSX1440 | Type1 | xref:3918 | True | False | 11 | other_named | Danksagungen; WasistTopologie? |
| CMR9 | Type1 |  | True | False | 10 | other_named | (0); =1 |
| SFRM0600 | Type1 | xref:3918 | True | False | 6 | other_named | 1; 2 |
| SFSX1200 | Type1 | xref:3918 | True | False | 6 | other_named | Aufgabe1(Sierpińskiraum); Aufgabe2 |
| SFSX2074 | Type1 | xref:3918 | True | False | 4 | other_named | Vorwort; Inhaltsverzeichnis |
| SFTI1095 | Type1 | xref:3918 | True | False | 4 | other_named | Spurtopologie; Unterraumtopologie |
| CMBX10 | Type1 |  | True | False | 4 | other_named | N; ˆP |
| XYATIP-Medium | Type1 |  | True | False | 3 | other_named | � |
| XYBTIP-Medium | Type1 |  | True | False | 3 | other_named | � |
| CMSY6 | Type1 |  | True | False | 2 | other_named | ⊆ |
| SFBX0800 | Type1 | xref:3918 | True | False | 2 | other_named | 1; 2 |
| LINE10 | Type1 |  | True | False | 2 | other_named | ���;  |
| SFBX1440 | Type1 | xref:3918 | True | False | 1 | other_named | EinführungindieGeometrieundTopologie |
| CMSY9 | Type1 |  | True | False | 1 | other_named | ≥ |

### pdflatex-forms.pdf
- path: `test_files/sample-files-main/010-pdflatex-forms/pdflatex-forms.pdf`
- sha256: `fc6265298caafffeee9dd2d7f3ae2e53ab9f61ec0561369429d442f731d339da`
- pages: 1 | text_class: **true_text** | approx_shows: 1

| BaseFont (clean) | Subtype | Encoding | emb | TU | shows | class | sample |
|---|---|---|---|---|---:|---|---|
| CMR10 | Type1 |  | True | True | 1 | other_named | NameCheckSubmit1 |

### google-doc-document.pdf
- path: `test_files/sample-files-main/011-google-doc-document/google-doc-document.pdf`
- sha256: `69f6b7f493b1bc55d518942976cbeadc4ec0a36f6d8a6dc24feffc516d35b2c9`
- pages: 1 | text_class: **true_text** | approx_shows: 59

| BaseFont (clean) | Subtype | Encoding | emb | TU | shows | class | sample |
|---|---|---|---|---|---:|---|---|
| ArialMT | Type0/CIDFontType2 | Identity-H | True | True | 45 | specialty_other | Example document; Beautiful is better than ugly. |
| Arial-BoldMT | Type0/CIDFontType2 | Identity-H | True | True | 9 | specialty_other | Indonesia; Germany |
| Type3 (8 0 R) | None | None | None | None | 3 | specialty_other | 󰏙; 󰎲 |
| Arial-ItalicMT | Type0/CIDFontType2 | Identity-H | True | True | 1 | specialty_other | right |
| Type3 (9 0 R) | None | None | None | None | 1 | specialty_other | 󰎈 |

### libreoffice-form.pdf
- path: `test_files/sample-files-main/012-libreoffice-form/libreoffice-form.pdf`
- sha256: `9105eeef8c8cafdb141b7edd768a5e08adffe320d1d4f89e1a7112a2b37d1c57`
- pages: 1 | text_class: **true_text** | approx_shows: 14

| BaseFont (clean) | Subtype | Encoding | emb | TU | shows | class | sample |
|---|---|---|---|---|---:|---|---|
| Ubuntu | TrueType |  | True | True | 7 | other_named | First Name; Last Name |
| LiberationSerif | TrueType |  | True | True | 4 | other_named | Gender:; Nationality: |
| Helvetica | None | None | None | None | 2 | defaultish | Alice; Bob |
| LiberationSans-Bold | TrueType |  | True | True | 1 | other_named | Example for a Form |

### reportlab-overlay.pdf
- path: `test_files/sample-files-main/013-reportlab-overlay/reportlab-overlay.pdf`
- sha256: `fdbdd49a118053577240850826a7eff6ac4ce7288527bf4c483714f0113860ed`
- pages: 1 | text_class: **true_text** | approx_shows: 3

| BaseFont (clean) | Subtype | Encoding | emb | TU | shows | class | sample |
|---|---|---|---|---|---:|---|---|
| Roboto-Regular | TrueType |  | True | True | 3 | other_named | Name: Foo Bar; Fingerprint: asdfSa2123 |

### mistitled_outlines_example.pdf
- path: `test_files/sample-files-main/014-outlines/mistitled_outlines_example.pdf`
- sha256: `362dc3cc03538e864841a08d2b7365daf926651a2fe2c343669e03c8ac33b1af`
- pages: 4 | text_class: **true_text** | approx_shows: 23

| BaseFont (clean) | Subtype | Encoding | emb | TU | shows | class | sample |
|---|---|---|---|---|---:|---|---|
| CMR10 | Type1 |  | True | True | 12 | other_named | 1; Hello,hereissometextwithoutameaning.Thistextshouldshow... |
| CMBX12 | Type1 |  | True | True | 10 | other_named | Contents; 1Foo |
| CMBX10 | Type1 |  | True | True | 1 | other_named | 1Foo22Bar23Baz24Foo25Bar36Baz37Foo38Bar49Baz4 |

### habibi-oneline-cmap.pdf
- path: `test_files/sample-files-main/015-arabic/habibi-oneline-cmap.pdf`
- sha256: `31b50622a8623723188bbb69385881c70ca8bedaa5099a19392c0d0afcccd8ee`
- pages: 1 | text_class: **true_text** | approx_shows: 4

| BaseFont (clean) | Subtype | Encoding | emb | TU | shows | class | sample |
|---|---|---|---|---|---:|---|---|
| DejaVuSerif | Type0/CIDFontType2 | Identity-H | True | True | 2 | specialty_other | حَبيبي h; abibi |
| TimesNewRoman | Type0/CIDFontType2 | Identity-H | True | True | 2 | specialty_other | ������; حَبيبي |

### habibi-rotated.pdf
- path: `test_files/sample-files-main/015-arabic/habibi-rotated.pdf`
- sha256: `56329f1e3cff5358f1f2aadcfac03467cce51b36b2e2daab9c14cef26f7ea536`
- pages: 4 | text_class: **true_text** | approx_shows: 16

| BaseFont (clean) | Subtype | Encoding | emb | TU | shows | class | sample |
|---|---|---|---|---|---:|---|---|
| DejaVuSerif | Type0/CIDFontType2 | Identity-H | True | True | 8 | specialty_other | حَبيبي h; abibi |
| TimesNewRoman | Type0/CIDFontType2 | Identity-H | True | True | 8 | specialty_other | ������; حَبيبي |

### habibi.pdf
- path: `test_files/sample-files-main/015-arabic/habibi.pdf`
- sha256: `1017c4559eb7d0ccf7d151a3f051c8c1da27a7c1dc8050b2b687e3d3228e1b6f`
- pages: 1 | text_class: **true_text** | approx_shows: 4

| BaseFont (clean) | Subtype | Encoding | emb | TU | shows | class | sample |
|---|---|---|---|---|---:|---|---|
| DejaVuSerif | Type0/CIDFontType2 | Identity-H | True | True | 2 | specialty_other | حَبيبي h; abibi |
| TimesNewRoman | Type0/CIDFontType2 | Identity-H | True | True | 2 | specialty_other | ������; حَبيبي |

### libre-office-link.pdf
- path: `test_files/sample-files-main/016-libre-office-link/libre-office-link.pdf`
- sha256: `bc38b458acd125c09fb7603cf0cca5d8737eea9fe353c2aef2c42b3db9cf9076`
- pages: 1 | text_class: **true_text** | approx_shows: 3

| BaseFont (clean) | Subtype | Encoding | emb | TU | shows | class | sample |
|---|---|---|---|---|---:|---|---|
| LiberationSerif | TrueType |  | True | True | 3 | other_named | This is; a link to an awesome blog |

### unreadablemetadata.pdf
- path: `test_files/sample-files-main/017-unreadable-meta-data/unreadablemetadata.pdf`
- sha256: `9900c4c7edaa0b950314f33d8946b1247e3eafeea893958be76e62a32e1cd38a`
- pages: 0 | text_class: **empty** | approx_shows: 0
- fonts_from_shows: _(none extractable)_

### base64image.pdf
- path: `test_files/sample-files-main/018-base64-image/base64image.pdf`
- sha256: `aaad90df16fce40ec768629d2135479b98f65b39bb27c7f80fb106393187d619`
- pages: 1 | text_class: **true_text** | approx_shows: 1

| BaseFont (clean) | Subtype | Encoding | emb | TU | shows | class | sample |
|---|---|---|---|---|---:|---|---|
| Helvetica | Type1 | WinAnsiEncoding | True | False | 1 | defaultish | Produced with a Trial Version of PDF Annotator - www.PDFA... |

### grayscale-image.pdf
- path: `test_files/sample-files-main/019-grayscale-image/grayscale-image.pdf`
- sha256: `3adfd74b88cebcdd46c83f9b1d86b6995700233126b53e2f1fcacb40eab2dc84`
- pages: 1 | text_class: **unknown_or_empty** | approx_shows: 0
- fonts_from_shows: _(none extractable)_

### output_with_metadata_pymupdf.pdf
- path: `test_files/sample-files-main/020-xmp/output_with_metadata_pymupdf.pdf`
- sha256: `8e52052b0d7242a6d3df844e0f24ed3c09ca36440761d1b00f85bbabc15f7369`
- pages: 1 | text_class: **true_text** | approx_shows: 1

| BaseFont (clean) | Subtype | Encoding | emb | TU | shows | class | sample |
|---|---|---|---|---|---:|---|---|
| Helvetica | Type1 | WinAnsiEncoding | True | False | 1 | defaultish | Hello, World! |

### crazyones-pdfa.pdf
- path: `test_files/sample-files-main/021-pdfa/crazyones-pdfa.pdf`
- sha256: `f05f2738a1fa8c1d2e1147881fe1a62516a7f8caaf784067790731f56df626c4`
- pages: 1 | text_class: **true_text** | approx_shows: 3

| BaseFont (clean) | Subtype | Encoding | emb | TU | shows | class | sample |
|---|---|---|---|---|---:|---|---|
| SFTI1440 | Type1 | WinAnsiEncoding | True | False | 1 | other_named | TheCrazyOnes |
| SFTI1200 | Type1 | WinAnsiEncoding | True | False | 1 | other_named | October14,1998 |
| SFRM0900 | Type1 | xref:19 | True | False | 1 | other_named | Herestothecrazyones.Themisﬁts.Therebels.Thetroublemakers.... |

### pdfkit.pdf
- path: `test_files/sample-files-main/022-pdfkit/pdfkit.pdf`
- sha256: `8820ba44cd62264fd561e921aacc214cee7ba76723f525d591cdb2104a87f0dd`
- pages: 1 | text_class: **true_text** | approx_shows: 5

| BaseFont (clean) | Subtype | Encoding | emb | TU | shows | class | sample |
|---|---|---|---|---|---:|---|---|
| DejaVuSans-Bold | Type0/CIDFontType2 | Identity-H | True | True | 3 | specialty_other | Header; Foo: |
| DejaVuSans | Type0/CIDFontType2 | Identity-H | True | True | 2 | specialty_other | bar; DEF |

### cmyk-image.pdf
- path: `test_files/sample-files-main/023-cmyk-image/cmyk-image.pdf`
- sha256: `5a5f76a951e403a5b357992789afc5164fd6c2914583741de7a1dd08ec029ab2`
- pages: 1 | text_class: **unknown_or_empty** | approx_shows: 0
- fonts_from_shows: _(none extractable)_

### annotated_pdf.pdf
- path: `test_files/sample-files-main/024-annotations/annotated_pdf.pdf`
- sha256: `c327f921abfba23a5c42d5c429ba99ded1cf5511521003aba6d2aff9c940d9cc`
- pages: 1 | text_class: **true_text** | approx_shows: 4

| BaseFont (clean) | Subtype | Encoding | emb | TU | shows | class | sample |
|---|---|---|---|---|---:|---|---|
| Helvetica | Type1 | WinAnsiEncoding | True | False | 4 | defaultish | Some text.; Line 1 |

### with-attachment.pdf
- path: `test_files/sample-files-main/025-attachment/with-attachment.pdf`
- sha256: `1c7e5f3bb3bbf9a2424cac84f46b17e5b62af0719d63b445c280c76634b316ba`
- pages: 1 | text_class: **true_text** | approx_shows: 1

| BaseFont (clean) | Subtype | Encoding | emb | TU | shows | class | sample |
|---|---|---|---|---|---:|---|---|
| CMR10 | Type1 |  | True | True | 1 | other_named | Loremipsumdolorsitamet,consetetursadipscingelitr,seddiamn... |

### multicolumn.pdf
- path: `test_files/sample-files-main/026-latex-multicolumn/multicolumn.pdf`
- sha256: `bdb495e95b3e1afae95013099dc59b0cea047f1fa70f677ee9cb33f10faa1c6c`
- pages: 3 | text_class: **true_text** | approx_shows: 11

| BaseFont (clean) | Subtype | Encoding | emb | TU | shows | class | sample |
|---|---|---|---|---|---:|---|---|
| CMR10 | Type1 |  | True | False | 5 | other_named | ThisisasampledocumentwithtwocolumnsﬁlledwithLoremIpsumtex... |
| CMBX10 | Type1 |  | True | False | 2 | other_named | CountryPopulation(millions)Area(km; )CapitalOﬃcialLanguage |
| CMR17 | Type1 |  | True | False | 1 | other_named | Two-ColumnDocumentwithLoremIpsum |
| CMR12 | Type1 |  | True | False | 1 | other_named | YourNameJanuary3,2024 |
| CMBX12 | Type1 |  | True | False | 1 | other_named | Abstract |
| CMBX7 | Type1 |  | True | False | 1 | other_named | 2 |

### corrupted.pdf
- path: `test_files/Test-PDF-Files-master/corrupted.pdf`
- sha256: `b330a57d0d2b48449375628b4ad5fed0988443a5ca74f7d6050f6971423be98a`
- pages: 0 | text_class: **empty** | approx_shows: 0
- fonts_from_shows: _(none extractable)_

### encrypted.pdf
- path: `test_files/Test-PDF-Files-master/encrypted.pdf`
- sha256: `1a7afb90b4f510141ae9b556af2389af840dc991f1973f170f773a889106862f`
- pages: 1 | text_class: **unknown** | approx_shows: 0
- error: `scan:document closed or encrypted`
- fonts_from_shows: _(none extractable)_

### not_encrypted.pdf
- path: `test_files/Test-PDF-Files-master/not_encrypted.pdf`
- sha256: `18dc07d4deecdba337912f360ac5ec4253e7610e4ab6478b570f0c0b015e5ecb`
- pages: 1 | text_class: **true_text** | approx_shows: 1

| BaseFont (clean) | Subtype | Encoding | emb | TU | shows | class | sample |
|---|---|---|---|---|---:|---|---|
| LiberationSerif | TrueType |  | True | True | 1 | other_named | Not encrypted pdf |

## veraPDF light unique fonts (names only)
Scanned 499 / 2887; unique BaseFonts: 44

Specialty/nondefault names seen in corpus sample (truncated):
- `AboriginalSerif` (other_named) ex: `test_files/veraPDF-corpus-staging/PDF_A-2b/6.2 Graphics/6.2.11 Fonts/6.2.11.4 Embedding/6.2.11.4.1 General/veraPDF test suite 6-2-11-4-1-t02-fail-e.pdf`
- `AdobeGothicStd-Bold` (nondefault_cjk_hei_other) ex: `test_files/veraPDF-corpus-staging/PDF_A-1a/6.3 Fonts/6.3.8 Unicode character maps/veraPDF test suite 6-3-8-t01-pass-f.pdf`
- `AdobeMingStd-Light-Identity-H` (other_named) ex: `test_files/veraPDF-corpus-staging/Isartor test files/PDFA-1b/6.3 Fonts/6.3.5 Font subsets/isartor-6-3-5-t01-fail-a.pdf`
- `AdobeNaskh-Medium` (other_named) ex: `test_files/veraPDF-corpus-staging/PDF_A-1a/6.3 Fonts/6.3.8 Unicode character maps/veraPDF test suite 6-3-8-t01-pass-b.pdf`
- `BMFGlossary-BlackCondensedOne` (other_named) ex: `test_files/veraPDF-corpus-staging/Isartor test files/doc/Isartor test suite manual.pdf`
- `CMEX10` (other_named) ex: `test_files/veraPDF-corpus-staging/PDF_A-1a/6.3 Fonts/6.3.8 Unicode character maps/veraPDF test suite 6-3-8-t01-fail-a.pdf`
- `CMMI12` (other_named) ex: `test_files/veraPDF-corpus-staging/PDF_A-1a/6.3 Fonts/6.3.8 Unicode character maps/veraPDF test suite 6-3-8-t01-fail-a.pdf`
- `CMMI8` (other_named) ex: `test_files/veraPDF-corpus-staging/PDF_A-1a/6.3 Fonts/6.3.8 Unicode character maps/veraPDF test suite 6-3-8-t01-fail-a.pdf`
- `CMR12` (other_named) ex: `test_files/veraPDF-corpus-staging/PDF_A-1a/6.3 Fonts/6.3.8 Unicode character maps/veraPDF test suite 6-3-8-t01-fail-a.pdf`
- `CMSY8` (other_named) ex: `test_files/veraPDF-corpus-staging/PDF_A-1a/6.3 Fonts/6.3.8 Unicode character maps/veraPDF test suite 6-3-8-t01-fail-a.pdf`
- `F1` (specialty_type3) ex: `test_files/veraPDF-corpus-staging/PDF_A-1b/6.3 Fonts/6.3.6 Font metrics/veraPDF test suite 6-3-6-t01-fail-a.pdf`
- `FreeMonoBold` (other_named) ex: `test_files/veraPDF-corpus-staging/PDF_A-2b/6.2 Graphics/6.2.11 Fonts/6.2.11.4 Embedding/6.2.11.4.2 Subset embedding/veraPDF test suite 6-2-11-4-2-t02-fail-a.pdf`
- `Geosymbol` (specialty_symbol) ex: `test_files/veraPDF-corpus-staging/Isartor test files/PDFA-1b/6.2 Graphics/6.2.3 Colour spaces/6.2.3.3 Uncalibrated colour spaces/isartor-6-2-3-3-t02-fail-h.pdf`
- `HelveticaCloneT3.winansi` (specialty_type3) ex: `test_files/veraPDF-corpus-staging/Isartor test files/PDFA-1b/6.3 Fonts/6.3.4 Embedded font programs/isartor-6-3-4-t01-fail-g.pdf`
- `IDAutomationHC39M` (other_named) ex: `test_files/veraPDF-corpus-staging/PDF_A-2b/6.2 Graphics/6.2.11 Fonts/6.2.11.6 Character encodings/veraPDF test suite 6-2-11-6-t02-fail-a.pdf`
- `KozMinPro-Bold` (other_named) ex: `test_files/veraPDF-corpus-staging/PDF_A-2b/6.2 Graphics/6.2.11 Fonts/6.2.11.4 Embedding/6.2.11.4.1 General/veraPDF test suite 6-2-11-4-1-t01-fail-d.pdf`
- `KozMinPro-Regular-Acro-UniJIS-UCS2-H` (other_named) ex: `test_files/veraPDF-corpus-staging/Isartor test files/PDFA-1b/6.3 Fonts/6.3.4 Embedded font programs/isartor-6-3-4-t01-fail-c.pdf`
- `KozMinProVI-Regular-UniJIS-UCS2-H` (other_named) ex: `test_files/veraPDF-corpus-staging/Isartor test files/PDFA-1b/6.3 Fonts/6.3.3 Composite fonts/6.3.3.1 General/isartor-6-3-3-1-t01-fail-a.pdf`
- `LMMono10-Regular` (other_named) ex: `test_files/veraPDF-corpus-staging/PDF_A-1a/6.3 Fonts/6.3.8 Unicode character maps/veraPDF test suite 6-3-8-t01-fail-b.pdf`
- `LiberationSans,Bold` (other_named) ex: `test_files/veraPDF-corpus-staging/PDF_A-1a/6.3 Fonts/6.3.8 Unicode character maps/veraPDF test suite 6-3-8-t01-fail-c.pdf`
- `LiberationSerif` (other_named) ex: `test_files/veraPDF-corpus-staging/PDF_A-1a/6.8 Logical structure/6.8.4 Natural language specification/veraPDF test suite 6-8-4-t01-fail-a.pdf`
- `LuciduxSans-Oblique` (other_named) ex: `test_files/veraPDF-corpus-staging/Isartor test files/PDFA-1b/6.3 Fonts/6.3.2 Font types/isartor-6-3-2-t01-fail-b.pdf`
- `MdSymbolA-Regular` (specialty_symbol) ex: `test_files/veraPDF-corpus-staging/PDF_A-1a/6.3 Fonts/6.3.8 Unicode character maps/veraPDF test suite 6-3-8-t01-fail-b.pdf`
- `Menlo-Regular` (other_named) ex: `test_files/veraPDF-corpus-staging/PDF_A-1a/6.3 Fonts/6.3.8 Unicode character maps/veraPDF test suite 6-3-8-t01-pass-a.pdf`
- `NSimSun` (nondefault_cjk_song) ex: `test_files/veraPDF-corpus-staging/PDF_A-2b/6.2 Graphics/6.2.11 Fonts/6.2.11.3 Composite fonts/6.2.11.3.2 CIDFonts/veraPDF test suite 6-2-11-3-2-t01-fail-a.pdf`
- `NimbusRomNo9L-Regu` (other_named) ex: `test_files/veraPDF-corpus-staging/PDF_A-1a/6.3 Fonts/6.3.8 Unicode character maps/veraPDF test suite 6-3-8-t01-pass-d.pdf`
- `OceanSansMM_648_475_` (other_named) ex: `test_files/veraPDF-corpus-staging/PDF_A-2b/6.2 Graphics/6.2.11 Fonts/6.2.11.4 Embedding/6.2.11.4.1 General/veraPDF test suite 6-2-11-4-1-t01-fail-b.pdf`
- `SourceSansPro-Light` (other_named) ex: `test_files/veraPDF-corpus-staging/PDF_A-2b/6.2 Graphics/6.2.11 Fonts/6.2.11.5 Font metrics/veraPDF test suite 6-2-11-5-t01-fail-a.pdf`
- `SymbolMT` (specialty_symbol) ex: `test_files/veraPDF-corpus-staging/Isartor test files/doc/Isartor test suite manual.pdf`
- `TrajanPro-Regular` (other_named) ex: `test_files/veraPDF-corpus-staging/PDF_A-2b/6.2 Graphics/6.2.11 Fonts/6.2.11.4 Embedding/6.2.11.4.1 General/veraPDF test suite 6-2-11-4-1-t02-fail-a.pdf`
- `Verdana` (other_named) ex: `test_files/veraPDF-corpus-staging/PDF_A-2b/6.2 Graphics/6.2.11 Fonts/6.2.11.6 Character encodings/veraPDF test suite 6-2-11-6-t03-fail-a.pdf`
- `Verdana-Bold` (other_named) ex: `test_files/veraPDF-corpus-staging/Isartor test files/doc/Isartor test suite manual.pdf`
- `Verdana-Italic` (other_named) ex: `test_files/veraPDF-corpus-staging/Isartor test files/doc/Isartor test suite manual.pdf`
- `Wingdings-Regular` (specialty_symbol) ex: `test_files/veraPDF-corpus-staging/Isartor test files/PDFA-1b/6.3 Fonts/6.3.7 Character encodings/isartor-6-3-7-t02-fail-a.pdf`
- `X` (specialty_type3) ex: `test_files/veraPDF-corpus-staging/PDF_A-2b/6.2 Graphics/6.2.11 Fonts/6.2.11.5 Font metrics/veraPDF test suite 6-2-11-5-t01-fail-c.pdf`

## Cross-check: documented cases
- `scripts/experiment_hvac_font_edits.py` CASES 1–10 → HVAC PMingLiU/Arial/JhengHei (see `output/pdf/manual-font-study/results.json`)
- `scripts/experiment_cad_font_edits.py` TEXT_CASES seq 31/38/57/60 → ECC DFKaiShu only
- CHB/[AIRPORT_CODE] VECTOR_CASES only
- No FangSong / SimSun / Trebuchet / YaHei / Aptos / Europa case_ids found in docs/scripts/results

Raw dumps: `raw_inventory.json`, `FINGERPRINTS.json`, `NONDEFAULT_CANDIDATES.json`