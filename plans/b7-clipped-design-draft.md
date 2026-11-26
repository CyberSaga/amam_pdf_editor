# B7 step 5 — CLIPPED relaxation: design DRAFT (no code; owner ruling 11-26 "CLIPPED 放寬")

Status: draft by Claude from plans/b7-design-astra.md section 3 and plans/b5-fill-topology-clipped-design.md.
NOT Astra-reviewed (quota out until 11-29). This is the riskiest correctness claim of B7: do not implement
before a review.

## Claim to prove
A row may drop CLIPPED (become movable) only when its whole ink is provably strictly inside the effective clip,
and the clip stays where it is.  Moving the row later is a separate precondition (ink_bbox + delta still inside).

## Pieces
1. Scan state clip_state = Unbounded | Rect(x0,y0,x1,y1) | Empty | Unknown (unrotated page space, float64).
   q saves, Q restores; W/W* intersect AFTER the terminating paint; the setter row itself stays SETS_CLIP.
   First version proves only: one non-degenerate "re", no other contour, axis-parallel after the construction CTM
   (negative w/h, reflection, exact 90 degrees normalised; no tolerance for slight skew).  Everything else
   (curves, holes, diamonds, sheared rects, text clip, unknown CTM) = Unknown; a later known rect never clears an
   ancestor Unknown; disjoint intersection = Empty.  Rows under Unknown/Empty keep CLIPPED.
2. Ink bound: fill = control points + implicit close; stroke = that + half_width * max(sqrt2, miter_limit, 1)
   where half_width includes the CTM's largest singular value; combined = union.  Unknown width, hairline without
   a sound bound, non-finite, or touching the edge keeps CLIPPED.  Ink rounds outward, clip rounds inward.
3. Evidence: sparse table clip_limits(path, rect_id, ink_bbox) in VectorIndex, counted in nbytes and in the child
   transport (a flag alone cannot validate a destination).
4. Both scanners (scan.py G, scan_fast.py F) must produce byte-identical tables (D15 stays: pure bytes scanner).
5. Pixel oracle: two hand-written fixtures (clip kept / clip removed), source + independently generated safe
   destination at 1x/2x/4x, whole-page pixel compare; negatives: destination outside, thick stroke whose centre
   line is inside but ink is not, sharp miter, hole, nested narrow clip.

## Open questions for the owner / Astra
- Is the first version (single axis-parallel rect) enough for the CAD corpus?  Measure the share of CLIPPED rows
  in the 5 CAD samples that a single-rect clip explains before building.
- Does selection/delete need any change?  Per the design: no (constructed geometry, setter not deleted).
- Order: step 6 (skipped mask) and step 7 (DTO) do not depend on this; supports_move keeps using the current flag
  until this lands.
