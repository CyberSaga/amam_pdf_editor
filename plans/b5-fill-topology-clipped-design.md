# B5 design: fill topology and CLIPPED (GPT-6.2-Astra, 2026-11-25)

Source: Astra, read-only, prompt in session scratchpad. Owner decisions are named at the end. Not implemented.

## Result

**B5 can use the existing `subpath` column for fill topology. Keep `CLIPPED` as “any active explicit clip.”** Two distinctions matter in implementation. A chord-only inside test can miss a genuinely painted cubic sliver. And a clipped path can be selectable for deletion even where the click lands on a hidden part of its geometry.

### 1. Fill topology

**Scanner contract.** Ratify `segments.subpath`. Use the existing `paths.seg_start` and `seg_count` to take one ordered path slice. Each run of equal `subpath` is one contour. For fill queries, add a virtual edge from each run’s last endpoint to its first if they differ. Never join two runs, even if their endpoints coincide. `re` already supplies four directed edges, including the orientation of negative dimensions. Across batches, carry the current path, subpath, first point, last point and winding total. Close only at a real subpath or path boundary. Fill requires no new column, offset table, or change to either scanner. [Scanner tables](C:/Users/wilson/Documents/amam_pdf_editor/model/vector_paths/scan.py:169) · [Existing topology fixture](C:/Users/wilson/Documents/amam_pdf_editor/test_scripts/test_vector_scan.py:1005)

**Click rule.** Prefilter editable rows by their outward-rounded boxes, then visit candidates in descending row order. For fill, grow the box by the query tolerance. For stroke, use `max(tolerance, line_width/2)` when width is finite, otherwise `tolerance`. Use the larger applicable radius for a combined paint.

| Paint | Fill test | Stroke test |
|---|---|---|
| `S`, `s` | — | Stored centreline |
| `f`, `F` | Non-zero | — |
| `f*` | Even-odd | — |
| `B`, `b` | Non-zero | Stored centreline |
| `B*`, `b*` | Even-odd | Stored centreline |
| `n` | — | — |

`b` and `b*` already close the current subpath for stroke. Earlier open subpaths close only for fill. On a combined paint, test stroke first, then fill. Either returns the same row once. A higher fill row beats a lower stroke row. [Paint codes](C:/Users/wilson/Documents/amam_pdf_editor/model/vector_paths/scan.py:59) · [Selection contract](C:/Users/wilson/Documents/amam_pdf_editor/plans/cad-vector-object-editing.md:78)

**Inside and boundary.** For query `(x,y)` and directed edge `(x0,y0) → (x1,y1)`, compute `D = (x1-x0)*(y-y0) - (y1-y0)*(x-x0)` over NumPy arrays. Add one where `y0 <= y < y1` and `D > 0`. Subtract one where `y1 <= y < y0` and `D < 0`. Reduce over the **whole path**. Non-zero hits when the sum differs from zero. Even-odd hits when it is odd. Horizontal and zero-length edges contribute no crossings. Separately accept a point on a nonzero outline edge, including its endpoints, or within inclusive outline tolerance. This includes the virtual fill closure. The half-open intervals count a ray through a shared vertex once. Use an exact-sign fallback for numerically ambiguous line determinants instead of a fixed coordinate epsilon.

**Cubic error.** I recommend one-sided error for fill clicks because the requirement says a true interior click must hit. The scanner’s existing `0.01 pt` chords are sufficient for D18 marquee selection, but raw winding on those chords fails that click requirement. For a fill candidate with cubics, virtually bisect each stored cubic chord at its parameter midpoint, evaluated from `cubics.pts` and the cubic’s `seg_start/seg_count`. Use those halves for winding. For their outline distance use `tolerance + 0.0025 pt`; use plain `tolerance` on straight and implicit closing edges. Halving the parameter interval quarters the scanner’s interpolation bound. A true interior displaced by flattening is caught by the outline test. An exterior point accepted by that allowance is at most `0.005 pt` beyond the requested distance from the scanned cubic. No finer geometry needs to be stored. [Scanner’s subdivision formula](C:/Users/wilson/Documents/amam_pdf_editor/model/vector_paths/scan.py:1010)

**Dots.** A zero-length dot contributes no fill area and gets no standalone fill-outline hit. For stroke-dot picking, the current tables lose information. Two streams with a dot at `(2,2)` versus `(2,8)` produced byte-identical values in **all five tables**. My recommendation, if the owner accepts the open “leftover dots” behavior, is to select a closed stroke dot by its constructed point. Add a sparse `(path, subpath, x, y)` table for `m h` and equivalent close-paints, in path/subpath order, and include all its points in the bbox even on dot-only paths. G emits from `_close`, F from its existing `dot` mask. Carry the table through transport and `nbytes`, and require F/G `tobytes()` equality. Preserve existing segment counts and `DEGENERATE`. A bare `m` supplies no stroke dot. **This schema change is for dot picking only.** [G’s current dot handling](C:/Users/wilson/Documents/amam_pdf_editor/model/vector_paths/scan.py:952) · [Owner’s open dot question](C:/Users/wilson/Documents/amam_pdf_editor/plans/cad-vector-object-editing.md:490)

**Cost.** `O(N + Kc)` for the path-box pass and the segments of surviving candidates, with early exit on the topmost hit. Use bounded NumPy batches, for example 65,536 edges. A single candidate can still contain all 4,000,000 segments. My generated four-million-edge crossing pass took **74 ms**, before box filtering or distance tests. The 50 ms gate applies to the product query on the named sample. [B5 acceptance](C:/Users/wilson/Documents/amam_pdf_editor/plans/cad-vector-object-editing-handoff.md:341)

**Red tests for `test_vector_index_queries.py`**

| Fixture | Required result at zero tolerance |
|---|---|
| Outer `0 0 20 20 re`, inner `5 5 10 10 re` | `(10,10)` hits non-zero, misses even-odd. `(2,2)` hits both. Reverse the inner ring and the centre misses both. |
| Star through `(10,19),(15,2),(2,13),(18,13),(5,2)` | Centre `(10,10)` hits non-zero only. Tip `(10,16)` hits both. `(1,1)` misses both. |
| Open triangle `(0,0) → (12,0) → (12,12)` | `(9,4)` hits fill, `(4,9)` misses. Closing diagonal `(5,5)` hits fill and misses an open hairline stroke. Horizontal edge `(6,0)` and vertex `(12,12)` hit. Ray extension `(-1,0)` misses. |
| Disjoint `0 0 4 4 re` and `12 0 4 4 re` | `(2,2)` and `(14,2)` hit. Gap `(8,2)` misses. Repeat with a batch break inside each contour and directly between contours. |
| `0 0 m 1 .009 2 .009 3 0 c h f` | `(1.5,.003)` hits and `(1.5,.015)` misses. The stored chord has `y=0` throughout. |
| Combined paints, dots and z-order | Parameterize all ten paint codes. Pin wide-stroke-only, fill-only and simultaneous hits, a higher overlapping fill, a mixed stroke dot away from the line, and a fill-only dot miss. |

### 2. `CLIPPED`

**Keep the owner’s 11-23 definition.** G and F retain their current flag logic. An explicit path clip takes effect after its terminating paint. A text clip takes effect at the qualifying `ET`. Children inherit it and `Q` restores the enclosing state. `SETS_CLIP` blocks selection of the setter. `CLIPPED` alone leaves `EDITABLE` intact. [G flag assignment](C:/Users/wilson/Documents/amam_pdf_editor/model/vector_paths/scan.py:965) · [F clip events](C:/Users/wilson/Documents/amam_pdf_editor/model/vector_paths/scan_fast.py:776)

For B5, click tests the constructed path using the rules above. Touch tests its constructed segments with the B5 box fast path. Contain tests its stored bbox. None intersects the query geometry with the active clip. **A hidden portion can therefore win the click.** Delete removes the entire selected paint span while retaining the clip setter. Move refuses a selection containing a `CLIPPED` row before changing any bytes. Other edit blockers still apply. [D18 and marquee semantics](C:/Users/wilson/Documents/amam_pdf_editor/plans/cad-vector-object-editing.md:79) · [Refusal table](C:/Users/wilson/Documents/amam_pdf_editor/plans/cad-vector-object-editing.md:165)

**Measured effect.** Counts below are page-content path rows, with one-based page numbers. “Full only” means every active clip covers the CropBox. “Narrow” means at least one active clip cuts it. The move columns count editable rows passing the **clip** gate under each definition. Delete eligibility is identical under both.

| File and page | Rows | `CLIPPED` | Full only | Narrow | Delete eligible | Move, any → narrow |
|---|---:|---:|---:|---:|---:|---:|
| `cad_vector/before.pdf` 1 | 414,510 | 0 | 0 | 0 | 414,510 | 414,510 → 414,510 |
| `ecc-dwg.pdf` 1 | 4,063 | 4,056 | 0 | 4,056 | 0 | 0 → 0 |
| `hvac-dwg.pdf` 1 | 421 | 167 | 0 | 167 | 198 | 198 → 198 |
| `hvac-dwg.pdf` 6 | 24,745 | 24,734 | 0 | 24,734 | 0 | 0 → 0 |
| `22060_A1_01_Plans.pdf` 1 | 53 | 51 | 0 | 51 | 52 | 1 → 1 |
| `issue16800.pdf` 1, structural engineering figure | 6 | 1 | 1 | 0 | 2 | 1 → 2 |
| `issue15220.pdf` 1, mixed-clip control | 155 | 130 | 15 | 115 | 134 | 4 → 19 |

The narrower definition releases **16 rows** in these pages. The engineering figure’s released row has no `PAGE_ANCHORED` bit. The mixed control uses `/CS0` resolving to `/ICCBased` and `/GS0` with `/SMask /None` and `/BM /Normal`, so those 15 also pass the design’s D21 resource rule. All 4,056 clipped `ecc-dwg` rows carry `IN_OC`. The first `hvac-dwg` clip starts `0.000008871 pt` inside the page, so even a small equality tolerance would change the definition.

**Why keep the current flag.** Two pages can have identical content and the same six frame numbers but different right CropBox edges. The same rectangle can cover one and narrow the other. D15’s scanner cannot distinguish them. Even with page dimensions, a page-sized bbox cannot prove coverage for a diamond, a ring with a hole, or text. If the owner later relaxes move eligibility, retain `CLIPPED` and add a separate parent-side exemption only for a proven covering rectangle at every active clip level. An unproved clip keeps the move refusal. [D15 scanner inputs](C:/Users/wilson/Documents/amam_pdf_editor/plans/cad-vector-object-editing.md:99)

**Red tests.** Keep bit `8` in the F fuzz flag-coverage assertion. Add deterministic F-admitted fixtures for an exact-page rectangle, an oversized rectangle, a narrowing rectangle, a page-bbox ring with a hole, nested full-inside-narrow scopes, and a text clip. Require byte equality on every F/G table, plus explicit expected flags. A scoped `W n` followed by a stroke and a post-`Q` stroke must give `[4,9,1]`. In B5, click and touch the hidden extension of that first stroke and expect its row. Contain must cover the whole constructed bbox. The setter stays unselectable. At the edit layer, pin delete of the entire stroke and atomic move refusal. [Existing flag-coverage test](C:/Users/wilson/Documents/amam_pdf_editor/test_scripts/test_vector_scan_fast.py:642)

## Evidence

- `.venv\Scripts\python.exe -I -B -` with `scan_page(..., accelerated=False)` → counted effective clip scopes at paint time, checked transformed geometry against the effective CropBox, and reconciled totals to the emitted `CLIPPED` bits. Every active chain in the table was classifiable.
- Isolated G/F topology probes with G’s line flush forced to one row → all five tables byte-equal on the seven fixtures. Observed star windings `−2, −1, 0`. Independent MuPDF grayscale samples for centre, tip and outside were `0,0,255` under `f` and `255,0,255` under `f*`.
- In-memory clip render → the stored stroke ran from `(0,5)` to `(80,5)`. Pixel `(5,5)` was black and `(50,5)` was white. The row flags were `9`, confirming that selection by constructed geometry and selection by visible pixels produce different answers.
- `git status --short --untracked-files=no` → clean.

## Not performed

No repository writes or pytest runs, as requested. The product-path 50 ms gate remains unmeasured. One additional candidate, `bug1753983.pdf`, was excluded after G returned `SCAN_ERROR: malformed number b'-'`.

## Fence log

The owner retains the decision to ratify `subpath`, approve standalone stroke-dot picking, and change the 11-23 clip policy. The one-sided cubic allowance is my proposed B5 decision.

## Verified

A painted cubic sliver defeated plain chord winding. Two different stroke-dot locations produced identical geometry tables. A real full-page clip blocked an otherwise movable engineering-figure row. Those counterexamples determine where B5 can rely on the existing index and where it needs an explicit rule.


## Owner decisions open
1. Ratify `segments.subpath` as the fill topology (no schema change for fill).
2. One-sided cubic allowance for fill clicks (0.0025 pt), Astra proposal.
3. Standalone stroke-dot picking: needs a new sparse dot table (schema change, F/G tobytes equal).
4. Keep CLIPPED = any active explicit clip (11-23 ruling), or relax move eligibility later with a parent-side covering-rectangle exemption.
