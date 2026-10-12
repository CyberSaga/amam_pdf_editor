# Save (儲存) Icon → Detailed SVG + Drawing-Process Recording (2026-10-12)

## Goal

Redraw `view/resources/function_icons/03_儲存.png` (purple floppy disk, white
metal shutter, label window with a peeking hamster, white rounded card) as a
highly detailed SVG with **1500–1700 drawing elements**, painted the way a human
illustrator works, and deliver a full video/animation of the drawing process.

Process requirements (from the request):

1. Sketch → big shapes & proportions → large color blocks → light/shadow
   relationships → progressive refinement (structure, light, detail) → overall
   check → adjust & finish.
2. Work in batches: after each batch, render the canvas, observe it, decide
   what to draw next.
3. Proportions, contours and connections are corrected *during* the drawing
   (observation and correction run through the whole process, not only at the end).

## Affected modules

- `view/resources/function_icons/svg/03_儲存.svg` (new asset)
- `view/icons.py` — SVG-first loading with PNG fallback (per
  `docs/design/function_icons/FUNCTION_ICON_TO_SVG_SPEC.md` "Implementation
  Recommendation")
- `test_scripts/test_theme_and_icons.py` — red-light tests for the loader
- `pyproject.toml` package-data — ship `resources/function_icons/svg/*.svg`
- Docs: `docs/ARCHITECTURE.md` (icons paragraph), `docs/PITFALLS.md`, `TODOS.md`

Drawing tooling (op-log studio, replay player, video renderer) lives outside
the production layers.

## Steps

1. Studio toolkit: op log (add / modify / remove / layer / gradient), per-batch
   snapshots, Chromium preview renders + reference overlay for observation.
2. Draw in observed batches, stage by stage; record each batch's observation
   and decision in the op log (these become the video captions).
3. Replay player (HTML) + deterministic frame capture → MP4.
4. Loader integration (test first), QtSvg render verification, docs.

## Constraints / decisions

- Final SVG must stay renderable by QtSvg (PySide6 ≥ 6.4): no `filter`,
  `mask`, `clipPath`, CSS classes or blend modes. Clipping is done
  geometrically (texture strokes generated inside their regions).
- "Drawing elements" = rendered shape elements (`path`, `rect`, `circle`,
  `ellipse`, `line`, `polyline`, `polygon`). Sketch/guide strokes are erased
  in the finishing stage and do not count toward the final total.
- Coordinate space `viewBox="0 0 512 512"`; light source top-left.

## Open questions

- None blocking. The detailed SVG deliberately exceeds the 24×24 small-icon
  spec (the request asks for maximal detail); the toolbar still downsamples it
  exactly like the existing PNG.

## Log

- 2026-10-12: Reference measured from the PNG (body 114×130 px of 214, shutter
  0.52 body width, label 0.61 body width, chamfer ≈ 0.19 body width).
- 2026-10-12: Drew 28 batches (2,481 ops: 1,703 adds, 539 modifications, 153 erasures,
  21 observation/compare steps). Corrections made mid-process: head shape (circle → clipped
  ellipse), ear joins, muzzle peak, inner-ear fold, inner-shadow spill (even-odd XOR → geometric
  difference), gloss-arc point ordering, beaded bevel strokes, hard-edged glazes, stepped drop
  shadow, eyelash-like fur boundary, ink "stitches", freckles (user feedback), shutter graying
  at small sizes, dusty paper fibers.
- Decision: final SVG 1,550 drawing elements / 1,656 XML elements; QtSvg vs Chromium mean
  pixel diff 0.5/255; parse 11 ms, render 17 ms at 512 px.
- Decision: loader is SVG-first with PNG fallback (only 03 has an SVG today).
- Decision: toolkit committed under `scripts/icon_studio/` (dev-only, pruned from sdist) with
  the session's batch scripts as the reproducible source; working state stays gitignored.
- Decision: the workflow doc is a project skill (`.claude/skills/svg-icon-drawing/`), tracked via
  a per-skill `.gitignore` exception so other local skills stay private.
- Done. Video: 5:12, 1080p30, 9.6 MB (capture 9,354 frames in 508 s).
