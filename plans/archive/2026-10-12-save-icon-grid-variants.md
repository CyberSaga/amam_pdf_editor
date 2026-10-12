# Save (儲存) Icon — 16/24/48 px Grid Designs + DPR-Aware Loading (2026-10-12)

## Goal

Draw the save icon separately for 16, 24 and 48 px (each with as few elements as stay
clearly legible), render toolbar icons per display scale factor, and keep the detailed
1,550-element `03_儲存.svg` as the large design.

## Affected modules

- `view/resources/function_icons/svg/03_儲存_16.svg`, `_24.svg`, `_48.svg` (new)
- `view/icons.py` — `svg_design_path`, per-scale `load_icon`, `SVG_GRID_BOUNDS`, `ICON_SCALES`
- `test_scripts/test_theme_and_icons.py` — red-first tests for design selection, per-scale
  crisp renders (SVG and PNG), per-grid viewBox safety, element caps
- `scripts/icon_studio/` — configurable canvas, `pixel_review.py`, SVG references, id guard;
  sessions `save_03_g16/g24/g48`
- Docs: ARCHITECTURE icons paragraph, PITFALLS (single-pixmap HiDPI blur), TODOS, skill §8

## Steps

1. Red tests (5 new + viewBox rule per grid) — failed for the expected reasons.
2. Studio: canvas size per session, QtSvg pixel review at 1×/1.25×/1.5×/2×.
3. Draw g24 (7 batches), g48 (5), g16 (4) with pixel review after each batch.
4. Implement per-scale `load_icon`; verify in `PDFView` under `QT_SCALE_FACTOR` 1/1.5/2.

## Decisions

- Thresholds by device pixels: <20 → 16-grid, <36 → 24-grid, <96 → 48-grid, else large design.
- Scale set 1, 1.25, 1.5, 1.75, 2 plus live screen ratios (2.5/3 only when such a screen is present);
  PNG-only icons also get per-scale pixmaps (they were blurry on HiDPI before); decoded PNG sources
  are cached across sizes, so loading all 33 icons costs ~130 ms for the first size, ~35 ms after.
- No card background in grid designs; line weights 1/1.5/2.5 (outline) and 1/1/1.5 (frames).
- No process video for these (not requested); the sessions replay deterministically.

## Log

- Corrections during drawing: g24 body 20×20 → 18×20, slot to whole pixels, inner frames
  1.5 → 1 px, face outline navy → warm brown (eyes fused with outline at 1×), separate window
  frame above the hamster; g48 label window narrowed to the original 0.61 ratio; g16 slot
  moved one column left of the 24 design's position.
- Found and fixed: element ids colliding with layer-group ids (duplicate XML ids).
- User review: "only the 48's style is satisfying; 16/24 lack the detail for that style". Redrew 16 and 24
  as pixel-placed miniatures of the 48 (sessions g24 b08–b12, g16 b05–b07): face area re-planned to the 48's
  proportions (24: 10×7, 16: 8×5 with a 14×14 body), outlines dropped where the frame bounds the head,
  peach kept dominant. Final counts 15 / 18 / 28. No process video (user: not needed for now).
