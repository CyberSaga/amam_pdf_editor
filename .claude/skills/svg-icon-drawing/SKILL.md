---
name: svg-icon-drawing
description: Redraw a toolbar icon (view/resources/function_icons/*.png) as QtSvg-safe SVG through an observed, human-like batch process (sketch → proportions → color blocks → light/shadow → detail → overall check → finish) — either a detailed large design with an element-count target or pixel-grid designs for 16/24/48 px — and record the process as a replay player + MP4. Use when asked to convert or redraw an icon as SVG, to make an SVG "as detailed as possible" or with N drawing elements, to draw small/HiDPI toolbar variants, or to produce a drawing-process video/animation.
---

# Detailed SVG icon drawing (observed batches + process video)

Worked example: `scripts/icon_studio/sessions/save_03/` (03_儲存, 28 batches,
2,481 ops, 1,550 drawing elements, 5:12 video). Read the batch scripts you need
as templates; do not rebuild the toolkit.

## 0. Acceptance — confirm before the first batch

- Output `view/resources/function_icons/svg/<NN>_<label>.svg`, `viewBox="0 0 512 512"`,
  `width/height=512` (the loader renders at intrinsic size, then downsamples).
- **Count rule:** "drawing elements" = rendered shapes (`path rect circle ellipse
  line polyline polygon`). Keep defs lean (save_03: 26 gradients / 67 stops) so the
  total XML element count is *also* inside the range (1,550 shapes / 1,656 total).
- **QtSvg-safe (PySide6 ≥ 6.4):** no `filter`, `mask`, `clipPath`/`clip-path`,
  `<style>`/`class`, blend modes. Clip geometrically with shapely instead.
  Allowed: linear/radial gradients (`userSpaceOnUse`), `stop-opacity`,
  `fill-rule`, `transform`, group `opacity`.
- Sketch/guide layers are erased in stage 7 and never count.
- Stay faithful to the reference silhouette and palette; added detail must not
  change what the icon depicts. Ask before adding new motifs.

## 1. Toolkit (`scripts/icon_studio/`)

| File | Role |
| --- | --- |
| `studio.py` | Op log: `add / mod / rm / layer / gradient / restack`, video-only `look / compare / thumbs`; per-batch snapshots; `commit()` renders previews |
| `geo.py`, `brush.py`, `kit.py` | Paths (arc-based outlines with fixed command sequences), offset rings, pressure strokes, scatter, pencil/guide strokes |
| `render.js` | Chromium rasterizer (Playwright) for previews |
| `player_template.html`, `build_player.py` | Op log → single-file replay player (captions, cursors, morphs, timeline) |
| `capture.js` | Player → MP4 (deterministic frames → ffmpeg) |
| `run_session.py` | Replay a session from scratch, export SVG / player / video |

```bash
# new session: sessions/<name>/session.json (title, reference, ref_map, output) + bNN.py files
python scripts/icon_studio/run_session.py <name> --step N          # draw batch N on the current state + previews
python scripts/icon_studio/run_session.py <name> --no-render --export   # replay all (~1 s) + write the SVG
python scripts/icon_studio/run_session.py <name> --no-render --video    # replay + player + MP4
```

Prerequisites (dev-only, not app dependencies): `pip install shapely` (Pillow is
already a runtime dep), Node with Playwright + Chromium (`npm i -D playwright`, or set
`PLAYWRIGHT_MODULE`), and ffmpeg for `--video`.

`ref_map` = `scale,dx,dy` mapping the reference PNG onto the 512 canvas; measure it
from the main body's bounding box with numpy before batch 1.

## 2. The batch loop (non-negotiable)

1. `s.begin(stage, title, observe, decide, tempo)` — `observe` states what the
   *last render* shows (concrete, measurable: "head top too pointed; widest at
   y≈338 in the reference"); `decide` states this batch's change. These become the
   video captions; write them in the user's language.
2. Ops: 5–30 for structural batches, 100–280 for texture batches (`tempo="rapid"`).
3. `s.commit(zooms=[(x, y, w, h)], compare=…, small=…)`, then **look at the
   zoom crop of what changed**, not the whole sheet. `compare=True` for proportion
   checks (onion skin over the mapped reference); `small=True` at the overall check.
4. Corrections are **new ops in a later batch** with a `note=` (they animate as
   visible fixes). `restore(n)` only for code errors, never to hide a judgment call.
5. Give every correction a `s.look(box, note)` so the video shows where you looked.
6. User feedback mid-run becomes the next batch's `observe` (save_03 b19: "移除雀斑").

## 3. Stage plan and element budget (save_03 actuals)

| Stage | Batches | What | Final elements added |
| --- | --- | --- | --- |
| 1 草稿 | b01–b02 | axes, block-in boxes, rough inner blocks | 0 (process only) |
| 2 大形與比例 | b03–b05 | reference onion-skin, row-by-row measurement, contour pencil | 0 |
| 3 鋪大色塊 | b06–b07 | flat local colors under the sketch, value anchor (eyes) | ~17 |
| 4 明暗關係 | b08–b10 | light top-left, gradients, cast shadows, recess shadows | ~15 |
| 5 細化 | b11–b26 | ink → edges → materials → focal point → fur → paper → grain | ~1,515 |
| 6 檢查整體 | b27 | small sizes + reference side by side; value/contrast fixes | 0 (mods) |
| 7 調整收尾 | b28 | erase sketch/guides, last glints | 3 |

Where 1,550 elements went: fur 564, plastic grain + scuffs 368, card grain 200,
brushed hairlines 154, paper fibers 110, face/parts 39, disk tracks 25, ink 20,
everything structural < 70. Plan the texture budget **per region before stage 5**
(area × density), so the total lands in range without last-minute padding.

## 4. Techniques that worked

- **Outlines:** build paths with fixed command sequences (`body_outline_d`,
  `rrect_d`, same point counts) so later corrections morph instead of crossfade.
- **Hole/recess shading:** `poly_d(inner_band(pts, dx, dy))` = hole − shifted hole
  (shadow inside top-left, rim light inside bottom-right).
- **Edge lighting:** one continuous `pressure_d` stroke per edge run, then 2–3
  shorter, brighter accents stacked toward the hot corner.
- **Glazes:** clip the polygon to the form (`.intersection(form.buffer(-2.5))`) and
  fill with a gradient whose 0-opacity stop lies *outside* the polygon edges.
- **Soft shadow without filters:** 8 stacked copies, offset (2,2.8)→(13.8,18.4),
  expanded 0→7.8, opacity 0.07→0.016.
- **Fur:** flow field (radiate from the nose, cheeks bend down) and three
  low-opacity passes: boundary interlock, shadow-side, fine. Keep strokes inside
  regions with `region.contains(LineString(...))`, avoid eyes/nose/mouth buffers.
- **Grain:** scatter inside the visible region minus occluders; light specks
  toward the light source, dark specks away; opacity ≤ 0.34.

## 5. Failure log (each cost a correction batch in save_03)

| Symptom | Cause | Fix |
| --- | --- | --- |
| Gray sliver outside a hole | even-odd of hole + shifted hole is a XOR; the shifted copy spills out | geometric difference (`inner_band`) |
| Gloss arc closed into a triangle | points sorted by `atan2` wrap at ±180° | take a contiguous run in ring order |
| Edge highlight looks like a bead chain | many short double-tapered segments | one continuous pressure stroke + accents |
| Crease line across the body | hard-edged glaze polygon / gradient not 0 at the edge | extend the polygon, move the 0 stop beyond it |
| Stair-steps in the drop shadow | only 4 stacked layers | 8 layers, smaller increments |
| Peach/white border reads as eyelashes | bright, regular, thick boundary strands | ×0.72 length, ×0.72 width, ×0.6 opacity, more angle jitter |
| Outline "stitches" | ink wisps perpendicular to the contour | remove; keep the reference's clean contour |
| Freckles | brown whisker-pad dots | remove (user feedback) |
| Shutter turns gray at 48–96 px | brushed hairlines too strong | opacity ×0.55, lighten the gradient's bottom stop |
| Paper looks dusty | fibers/dots too visible | opacity ×0.5, lighter color |

Re-check these at every texture batch; they are the defaults to avoid.

## 6. Efficiency and performance

- **Context:** never Read the SVG (≈360 KB); use `s.count()` and zoom crops
  (800 px). Keep each batch script < 120 lines; shared geometry in a session
  helper (`hamster_geo.py`).
- **Render cost:** a commit is one Chromium launch (~1.5–3 s); request the 2048 px
  render only when passing `zooms`. Use `--no-render` for replays (1.2 s for
  28 batches).
- **Video:** schedule is computed in the browser; `renderAt(t)` is incremental
  for forward time. JPEG q92 frames piped to ffmpeg (libx264, crf 20):
  9,354 frames in 508 s. Start the capture in the background and do other work.
- **Pacing:** tempo per batch (`slow` sketch → `rapid` textures) gives ~11 s per
  batch; 28 batches ≈ 5 min. Noted corrections play sequentially (1.25 s each).
- **Delegation:** the draw→look→decide loop needs your own visual judgment; do
  not hand it to a subagent. Tooling chores (lint, packaging) can be delegated.

## 7. Verification before reporting done

1. `run_session.py <name> --no-render` output is byte-identical to the committed SVG.
2. Shape count and total element count inside the requested range; grep for
   forbidden features (`<filter <mask clipPath clip-path <style class=`).
3. QtSvg render (`QSvgRenderer`, offscreen) vs Chromium render: similar pixels;
   small-size sheet (16–96 px) vs reference.
4. `pytest test_scripts/test_theme_and_icons.py` (SVG-first loader with PNG fallback).
5. Deliver: SVG, MP4, and the player HTML; state the counts and the corrections made.

## 8. Pixel-grid designs (16 / 24 / 48 px) — the toolbar sizes

Measured: at 24 px the 1,550-element design and a 109-element cut differ by 0.16/255
on average. Toolbar sizes need **separate designs on their own grid**, not detail.
Worked examples: `sessions/save_03_g48` (28 elements), `save_03_g24` (18), `save_03_g16` (15).

**Style comes from the 48 grid; carry it down, don't swap it.** The first 16/24 versions
were simplified pictograms (warm-brown outlines, no muzzle, plain eyes) and the user
rejected them: only the 48's style was acceptable. Draw the 48 first, then port its
ingredients to 24 and 16 *pixel by pixel* — navy-tipped ears with pink insides, 2×2 eyes
each with a 1-px white catchlight, white muzzle (peak between the eyes at 24), blush,
nose, body gloss + shadow side. Halving coordinates (`x/2, y/2−1` for the face) gives the
starting layout; vector strokes thinner than 1 px turn the face gray, so place the face as
whole-pixel rects. Give the face the 48's proportion of rows: 7 rows at 24, 5 at 16
(the 16 body widens to 14×14 to make room).

- One session per grid: `session.json` gets `"canvas": 16|24|48`, output
  `<stem>_<grid>.svg`, and may use the large SVG (or the next grid) as `reference`.
- After every batch run the QtSvg pixel review (the app's renderer, not Chromium):
  `.venv/bin/python scripts/icon_studio/pixel_review.py work/<session>/out/final.svg --grid 24 --out sheet.png [--compare other.svg old.png]`
  → magnified 1× / 1.25× / 1.5× / 2× rasters with a pixel grid + real-size tiles on light/dark.
- Budget rows and columns before drawing (16 px: outline, 3 shutter rows, frame, 1 purple
  row, frame, 4 label rows, frame, 1 purple row, outline). Every frame needs ≥ 1 px of
  body color between it and the next dark line, or they fuse.
- Outer edges on whole pixels: stroke centered on a path inset by stroke/2 (1 px stroke
  → `.5` coordinates). Small features (slot, eyes) on whole pixels too — a 2 px slot on
  half-pixel edges smears into a 3 px gray column.
- Line weights used: body outline 1 / 1.5 / 2.5 px, inner frames 1 / 1 / 1.5 px (16/24/48).
- Dark budget on tiny faces: drop outlines wherever the window frame already bounds the
  head (a 1 px side outline next to the frame reads as a 2 px black bar / mask); keep the
  ear tips, the eyes and (at 24) a one-row shoulder turn. Keep the hamster color dominant:
  at 16 px the first port was a black-and-white checkerboard with 6 peach pixels; moving
  the forehead and the gap between the eyes back to peach (10 px) fixed it.
- Check the 24 design at the ribbon's real sizes (28 / 32 px): there it beat the 48 design
  shrunk down, which is why `_24` covers device sizes up to 35 px.
- Put the window frame in a layer above the contents as its own element; a closed head
  path otherwise strokes its cut edge.
- Element ids must not equal layer names (`body`, `shutter`, `label` …) — duplicate XML ids;
  `Studio.add` now refuses them.
- Loader contract: `svg_design_path` picks `_16` below 20 device px, `_24` below 36, `_48`
  below 96, else the large `<stem>.svg`; `load_icon` renders every scale factor (100–200 % steps + present screens)
  from the matching design, so a 24 px icon on a 150 % screen is a real 36 px render.
