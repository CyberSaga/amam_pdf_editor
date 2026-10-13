# Function icons → SVG (remaining 32 toolbar icons)

## Goal

Redraw the 32 ribbon icons that still render from PNG as QtSvg-safe pixel-grid SVG
designs (`<stem>_16.svg`, `<stem>_24.svg`, `<stem>_48.svg`) in the style the user
approved for 03_儲存: the 48 px design sets the style, the 24 and 16 px designs carry
it down pixel by pixel. Compositions follow `docs/design/function_icons/_contact_sheet.png`
(the user picked this version over `_contact_sheet_redrawn.png`); it is a montage of the
current PNGs 01–31 plus `icon_32.png` (a link icon the app does not use).

## Scope decisions

- Icons: every `ACTION_ICON_MAP` entry except 儲存 (done) — 01, 02, 04–31, 33, 34.
  33 拉正頁面 and 34 適應畫面 are not on the contact sheet: their PNGs are the reference.
  Contact-sheet icon 32 (link) has no toolbar action: not drawn.
- Grid designs only. No 1,500-element large designs (the save icon's large design took a
  full session; toolbar sizes never reach it below 96 device px). For ≥ 96 device px an
  icon without a large design renders from its largest grid design (vector, still crisp)
  instead of falling back to the PNG card art (a different style).
- No process video for now (user, 2026-10-12). Sessions still replay byte-identically, so
  a player/video can be built later.
- Where the app shows them: ribbon 28 px (icon only) / 32 px (text under icon), 24 px on
  two QPushButtons. Device px: 100 % → `_24` at 24–32 px (scaled up to 1.33×), 125 % →
  `_24` up to 35 px then `_48`, 150–200 % → `_48` at 36–64 px. `_16` serves < 20 px.

## Affected modules

- `view/icons.py` — `svg_design_path` falls back to the largest grid design above the
  grids (and below them, the nearest smaller grid); `svg_icon_path` returns the most
  detailed design. No API change.
- `test_scripts/test_theme_and_icons.py` — coverage test (every mapped icon has three grid
  designs), fallback tests, caps over every grid SVG, PNG-only tests moved to an empty
  SVG dir (no real action is PNG-only any more).
- `view/resources/function_icons/svg/` — 96 new SVGs.
- `scripts/icon_studio/` — per-session layer list (`session.json` `"layers"`), shared parts
  (`parts.py`: palette, pixel maps, hamster heads per grid, page, plus badge), 96 sessions.
- Docs: `docs/ARCHITECTURE.md` §2.5, `docs/PITFALLS.md`, `TODOS.md`, skill §8.

## Style sheet (from 03_儲存 grid designs + reference palette)

| Token | Value | Use |
| --- | --- | --- |
| INK | `#1E1D38` | every outline, eyes |
| PEACH / EAR_IN | `#F6C58E` / `#F2A3A0` | hamster fur / inner ear |
| BLUSH | `#F48FA0` @ .55 (48), `#F6A3B0` (24/16) | cheeks |
| NOSE | `#E35D6A` (48), `#EC7684` (24/16) | nose |
| PURPLE / _LIGHT / _DARK | `#9285D5` / `#B9AEEB` / `#6A5EB6` | arrows, badges, floppy, tiles |
| TEAL / _DARK | `#7DD3C9` / `#3E9E95` | export arrow, handles, beams, iris |
| YELLOW / _DARK | `#FDD978` / `#E3B04B` | folder, notes, highlighter |
| RED | `#D9434A` | PDF mark, delete X |
| PAPER / PAPER_SHADE / LINE | `#FFFFFF` / `#E6E5F0` / `#B3AFD6` | pages, page lines |

Line weights (48 / 24 / 16): object outline 2.5 / 1.5 / 1, inner lines 1.5 / 1 / 1,
hamster outline 1.25 / 1 px pixels / 1 px pixels. Outer edges on whole pixels.
Hamster: navy-rimmed ears with pink insides, peach head, white muzzle, eyes with a white
catchlight, nose, blush; whiskers and mouth only at 48. The function symbol stays the
dominant shape; the hamster is the brand cue (spec: FUNCTION_ICON_TO_SVG_SPEC.md).

## Steps

1. Red tests, then the loader fallback (green except coverage).
2. Toolkit: session layers, `parts.py`.
3. Per icon: `<slug>_g48` (sketch/blocks → form/light → hamster/detail → check), then
   `<slug>_g24` and `<slug>_g16` ports; QtSvg `pixel_review.py` after every batch, plus a
   set sheet every few icons to keep weights and sizes consistent across the set.
4. Set review at real sizes (24/28/32/48/64 px, light + dark), ribbon screenshot at
   100/150/200 %.
5. Replay all sessions byte-identically; tests, ruff, lint-imports; docs; archive plan.

## Icons (composition from the reference → session slug)

| # | Label | Slug | Composition | 48 | 24 | 16 |
| --- | --- | --- | --- | --- | --- | --- |
| 01 | 開啟 | open_01 | yellow folder, PDF page behind right, hamster in folder waving | ✓ 25 | ✓ 13 | ✓ 13 |
| 02 | 列印 | print_02 | printer body, paper out with lines, hamster on top holding paper | | | |
| 04 | 另存新檔 | saveas_04 | purple floppy (label lines), hamster peeking left, plus badge | ✓ 33 | ✓ 19 | ✓ 15 |
| 05 | 另存為最佳化的副本 | optimize_05 | page + PDF mark + lines, inward arrows L/R, hamster on top | ✓ 28 | ✓ 15 | ✓ 14 |
| 06 | 瀏覽模式 | browse_06 | navy cursor with white rim, hamster face inside | | | |
| 07 | 操作物件 | select_07 | frame with teal corner handles, hamster bottom-right holding a handle | | | |
| 08 | 復原 | undo_08 | purple curved arrow left, hamster on top | | | |
| 09 | 重做 | redo_09 | purple curved arrow right, hamster inside the curve | | | |
| 10 | 全螢幕 | fullscreen_10 | four purple diagonal arrows out, hamster face center | | | |
| 11 | 縮圖 | thumbs_11 | framed 2×2 tiles (purple/teal), hamster on top | | | |
| 12 | 搜尋 | search_12 | magnifier, hamster face in lens | | | |
| 13 | 快照 | snapshot_13 | camera in corner brackets, hamster on top | | | |
| 14 | 編輯文字 | edittext_14 | serif T, text cursor, hamster holding the cursor | | | |
| 15 | 新增文字框 | textbox_15 | box with handles, T, hamster top-left, plus badge | | | |
| 16 | 矩形 | rect_16 | rectangle frame, hamster bottom-left with pen | | | |
| 17 | 螢光筆 | highlight_17 | yellow highlighter + stroke, hamster on top | | | |
| 18 | 新增註解 | note_18 | yellow note bubble with lines, hamster left, plus badge | | | |
| 19 | 插入圖片 | image_19 | picture frame (sky, hills, sun), hamster bottom, plus badge | | | |
| 20 | 貼上圖片 | paste_20 | clipboard with picture, hamster on top | | | |
| 21 | 註解列表 | notes_21 | three bubbles (yellow, teal, purple), hamster left | | | |
| 22 | 添加浮水印 | watermark_22 | page with drop, stamp, hamster on top, plus badge | ✓ 31 | ✓ 16 | ✓ 15 |
| 23 | 浮水印列表 | watermarks_23 | stacked pages with drop, hamster right | ✓ 25 | ✓ 13 | ✓ 13 |
| 24 | 顯示/隱藏註解 | togglenotes_24 | eye (teal iris), minus badge, hamster on top | | | |
| 25 | 刪除頁 | delpage_25 | page with red X, trash can, hamster left | ✓ 36 | ✓ 19 | ✓ 15 |
| 26 | 旋轉頁 | rotate_26 | page with purple circular arrow, hamster on top | ✓ 26 | ✓ 13 | ✓ 12 |
| 27 | 匯出頁 | export_27 | page, teal arrow out right, hamster right | ✓ 25 | ✓ 13 | ✓ 12 |
| 28 | 插入空白頁 | blank_28 | blank page, hamster right, plus badge | ✓ 26 | ✓ 16 | ✓ 12 |
| 29 | 從檔案插入頁 | insertfile_29 | folder, page with lines, teal arrow, hamster in folder | ✓ 30 | ✓ 15 | ✓ 13 |
| 30 | 合併PDF | merge_30 | two PDF pages → purple arrows → stack, hamster middle | ✓ 36 | ✓ 20 | ✓ 15 |
| 31 | OCR（文字辨識） | ocr_31 | scanner bar, teal beam, brackets, T, ghost hamster | | | |
| 33 | 拉正頁面 | deskew_33 | tilted page, teal guides, brackets, purple arrow, hamster top | ✓ 36 | ✓ 17 | ✓ 15 |
| 34 | 適應畫面 | fit_34 | page, corner brackets with teal arrows in, hamster bottom-left | ✓ 32 | ✓ 16 | ✓ 16 |

## Parallel split (2026-10-13, user asked for parallel workers)

Shared brief for the workers: scratchpad `agents/BRIEF.md` (workflow, tools, files they may touch —
only their own sessions and SVGs; parts.py is frozen for them). Lead reviews every icon before commit.

| Worker | Icons |
| --- | --- |
| icons-arrows | 06 browse, 08 undo, 09 redo, 10 fullscreen |
| icons-text | 07 select, 14 edit text, 15 text box, 16 rectangle |
| icons-notes | 17 highlighter, 18 add note, 21 note list, 24 show/hide notes |
| icons-image | 11 thumbnails, 13 snapshot, 19 insert image, 20 paste image |
| icons-misc | 02 print, 12 search, 31 OCR |
| lead | 01 open, 04 save as, 34 fit to view (+ review, docs, commit) |

## Decisions and dead ends

- 28 calibrated the set (2026-10-12):
  - Object outline 2.5 px at 48 matches the floppy's weight at real size — keep it for every
    main object even where the reference line is thin.
  - 48 hamster = `parts.hamster48` (k ≈ 0.73 for a 14 px head, may tilt with `rot`); a peeking
    hamster sits in a layer below the object, paws in a layer above it.
  - 24 px: a free-standing pixel head boxed in navy with a V chin reads as a black-masked cat
    (10 variants tried). The chubby head+body "bean" (`parts.BEAN24`), widest at the cheeks,
    left outline hidden under the object's edge, reads as the 03_儲存 hamster.
  - 16 px: `parts.FACE16` — no side outlines, one muzzle row; an outlined right side turns the
    face into a black box.
  - Plus badge per grid (`parts.badge_plus`): 48 outer r 6.5 / 1.5 ring / 3-px plus; 24 outer
    r 4 / 1 px ring / 5×5 plus; 16 outer r 3.5 / 1 px ring / 5×5 plus. Smaller rings or 3×3
    pluses stop reading as "add".
  - Keep the hamster's ears clear of other dark strokes (the 24 left ear fused with the
    page's fold diagonal).
