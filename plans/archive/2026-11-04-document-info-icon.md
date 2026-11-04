# 文件資訊 ribbon icon

**Goal.** User request (2026-11-04): "以同樣風格新設計現在缺的「文件資訊」按鈕，繪製成 SVG" — the 檔案 tab's
文件資訊 action (opens the metadata editor) is the only ribbon button without an icon. Design one in the
set's style (03's hamster, navy ink, purple function colour) on the 48 / 24 / 16 grids.

**Affected.** `view/icons.py` (`ACTION_ICON_MAP` entry), `view/resources/function_icons/35_文件資訊.png`
(fallback raster), `view/resources/function_icons/svg/35_文件資訊_{16,24,48}.svg`,
`scripts/icon_studio/sessions/docinfo_35_g48|g24|g16/`, `test_scripts/test_theme_and_icons.py`, the icon
skill, TODOS.

## Steps

1. Red tests: the map covers 文件資訊 (34 entries), and the ribbon's 文件資訊 action ends up with an icon.
2. Prototype layouts at 48 / 24 / 16 (throwaway SVGs) and compare them with the 檔案 tab neighbours.
3. Draw the 48 design in observed batches, then port it to 24 and 16 (one session per grid).
4. Fallback PNG rendered from the 48 design; map entry; tests green.
5. Real ribbon at 100 % / 200 %, docs, commit.

## Decisions

- **Number 35, not the free 32**: `docs/design/function_icons/icon_32.png` is the original set's link icon
  (no ribbon action); reusing 32 would point the design docs at the wrong picture.
- **Concept**: a page with metadata field rows (lavender key chip + value line), 03's hamster peeking over the
  page's top-left edge with its paws on it, a purple info badge with a white "i" at the bottom-right —
  the badge family of the set (+ add, − hide, i info). Diagonal hamster / badge so it differs from 05
  (hamster on top centre, PDF mark) right next to it and from 26 / 28 (page + hamster, + badge).
  Rejected: hamster on top centre (reads as 26), bean hamster beside the page (body cut by the page),
  an "i" inside the page (26's grammar, confusable with 旋轉頁 at 16).
- **Badge size**: larger than the plus badge (48: outer r 8.5 vs 6.5) because the "i" is the function cue;
  the glyph needs a dot, a gap and a longer stem.
- **24 glyph**: dot 2×2, one-row gap, stem 2×3, one row of purple above and below (b02 correction:
  the first port's 4-row stem ran into the ring and sat half a pixel low; moving the disc down blurred its
  top and bottom rows, moving the glyph up glued the dot to the ring).
- **16 badge as pixels**: an 8×8 pixel disc with a 2-px "i" (dot 1 row, gap, stem 3 rows down to the
  ring). The vector disc of the 16 plus badges left the dot touching the ring's antialiasing; a 2-row stem
  (centred) barely read longer than the dot.
- **Fallback PNG**: the 48 design rendered at 214 px (transparent). There is no card art for this icon,
  and the PNG is only shown when the SVG cannot be read.

## Result

- 48: 34 elements, 4 batches (sketch, blocks, details, overall check). 24: 15 elements, 2 batches
  (port, glyph correction). 16: 14 elements, 1 batch. All three replay byte-identically.
- Real ribbon at 100 % and 200 % (`PDFView`, `QT_SCALE_FACTOR` 1 / 2): the 檔案 tab shows the icon between
  另存新檔 and 另存為最佳化的副本 at the neighbours' weight.

## Dead ends

- Vector badge disc at 16 px (as the plus badges): the "i" dot fused with the ring's antialiased edge.
- Hamster on the page's top centre: the same silhouette as 05 (next to it in the ribbon) and 26.
