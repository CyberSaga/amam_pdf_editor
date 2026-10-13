# Bigger hamster ears across the icon set

**Goal.** User feedback (2026-10-13): "hamsters' ears are all too small. make ears 1.5~2x bigger." Apply it
to every hamster: the 48/24/16 grid designs of all 33 ribbon icons and the large `03_儲存.svg`.
(Same message: navy outlines fading on the dark theme are fine, so that follow-up was closed.)

**Affected.** `scripts/icon_studio/parts.py` (new ear parameter and correction helpers),
one new batch at the end of each of the 100 sessions in `scripts/icon_studio/sessions/`, the 100 SVGs in
`view/resources/function_icons/svg/`, the icon skill, TODOS. No application code changed.

## Steps

1. Prototype ear sizes on 03_48 (1.5×, 1.75×, 2×, wider spacing) and on the whole 48 set (1.5×, 1.65×).
2. `parts.py` (append-only): `_ear_geom` + `ears=` on `hamster_face48` / `hamster_bean48` /
   `hamster_face_px` / `hamster_bean_px` (default `SMALL_EARS` reproduces the old output — verified by
   replaying all 100 sessions), `BIG_EARS`, `grow_ears`, `shift_d` / `shift_ids`, `move_to_layer`,
   `px_cells` / `px_path` / `grow_ears_px`.
3. Generate an ear batch for every 48/24 session (`grow_ears`), export, review the set enlarged and at
   real size, then fix placement icon by icon inside the same batch.
4. 03_24 (03's own pixel face) and the 16 px pixel faces by hand-picked pixel patterns.
5. Large 03: one transform per ear group.
6. Verify (replay all sessions; replay each without its newest batch against `HEAD`; ruff; icon tests;
   real ribbon at 100 % / 200 %), docs, commit.

## Decisions

- **Ear geometry `BIG_EARS = (1.6, 0.7, 0.35, 0.15, -0.45, 2.7)`** (k units): radius ×1.6, centre 0.7k
  out and 0.35k up. The visible ear grows ~1.6× wide and ~1.75× tall, inside the requested 1.5–2×; the
  two ears stay apart over the dome; in 03 the ear's outline just reaches the label frame, so 03 keeps
  its proportions. 1.65× pushed 03's ears past the frame.
- **Pink inner ear moved, not scaled in place**: scaled about the old offset it sat behind the dome and
  the big ears read as plain peach discs. Now 0.15k out / 0.45k up, radius 2.7k.
- **One geometry for the whole set**, placement fixed per icon instead of per-icon ear sizes:
  48 — 06 head rebuilt at k 0.68 (the cursor rim hid the ears), 30 PDF pages moved behind the hamster,
  18/21/23/25 shifted sideways and 26 down (ears off the canvas). 24 — whole-pixel shifts (04, 07, 14,
  18, 21, 23, 25, 27, 28, 34 sideways), 13/20/22 moved down with their camera / whole drawing / stamp,
  30 pages behind the hamster; 05/11/17/26 keep a ≤ 0.35 px crop of the ear outline at the canvas top.
- **16 px pattern "V2"**: each ear one pixel wider outward with the 2 px navy tip moved out (round ears
  at the head's corners). Flat 3 px tips read as a head band; widening only the pink looked lopsided.
  `hidden=` keeps the inner tip pixel where an object covers the new outer column (04, 12, 14, 23).
- **03_24**: 3-wide, 3-row ears (pink 3×2) inside the 10×7 window; the vector head with big ears was
  muddy at that size.
- **Large 03**: `transform="matrix(1.6 0 0 1.6 tx ty)"` per ear group (base, outline, fur, highlight;
  inner ear, veins and fold get an extra shift up and out), stroke widths divided by 1.6, the outline arc
  closed into a full circle (the head hides the rest).

## Dead ends

- Moving top-edge 24 px peeking hamsters down 1 px: the object's top edge then covered the nose row
  (05, 11, 13, 20, 22, 26). Reverted; only 13/20/22 moved, together with their objects.
- Moving 03_48's label frame behind the hamster: no visible gain, since only the ear's own outline met
  the frame. Dropped.
