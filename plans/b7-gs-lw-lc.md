# B7 follow-up: resolve ExtGState /LW and /LC for the vector index (separate round, owner go-ahead 2026-11-28)

## Current state (at most 40 lines)
- Owner 11-28: "gs 的 /LC、/LW 允許另開一輪". Design by Astra (effort xhigh) below; NOT implemented.
- Today: a gs sets width and cap to NaN in scan.py and scan_fast.py (only the centre line is selectable, no round dots).
- The design needs more than the table lookup: (1) the resolved table must be part of the source identity (stream digests + frame + ExtGState digest), carried on the index, the selection and the plan, checked before the first write; (2) a stricter click test for strokes that gain hits, because the current circular radius already selects blank pixels (Astra probe: a point 2 pt past a butt end, and the narrow side of an anisotropic dot, were selected by both scanners and rendered white by MuPDF).
- Child job schema 2 (payload head with the table and its digest), index schema 2, limits.
- Owner decisions before implementation:
  1. The dictionary allowlist (Astra: /LW, /LC, optional /Type, valid /ca; anything else -> NaN as today).
  2. Resource budgets (Astra: 8 page-tree hops, 4 indirect hops, 4,096 entries, 127-byte names, 1 MiB table, 4 MiB head) and whether an over-budget page refuses or keeps today's bytes-only selection.
  3. Whether the stricter hit test (segment strip within its endpoints, dot radius in user space) also replaces today's test for paths without gs (it fixes the over-select past a butt end).
- Next step after the decisions: red-light tests in the order of section 5 below.

## Design (Astra, xhigh; paths made relative)

## Result

Resolve `/LW` and `/LC` on the model thread and pass an immutable snapshot to both scanners. **Two changes are necessary for this to be safe:** bind the snapshot to the index and delete plan, and give newly resolved strokes a stricter click test. Feeding a resolved width directly into today’s click radius selects demonstrably blank pixels.

### 1. Resolution and graphics-state semantics

- Capture the effective `/Resources/ExtGState` alongside the streams and frame in one GUI-thread read. Use the nearest page or `/Pages` ancestor that supplies `/Resources`. A local empty dictionary shadows the parent entirely. Follow ordinary indirect references with cycle and depth limits. The scanner receives only page `/Contents` and does not descend through `Do`. A form may reuse `/G` with a different definition without affecting the page lookup. Future form scanning would require a separate snapshot per invocation scope. [pdf_model.py:4335](model/pdf_model.py:4335) · [pdf_content_ops.py:428](model/pdf_content_ops.py:428) · [plan.py:1325](model/text_commit/plan.py:1325) · [scan.py:124](model/vector_paths/scan.py:124)
- Use **typed MuPDF objects** for the dictionary and its values. In the installed build, `xref_object_exact` prints PDF real `/LC 1.0` as `/LC 1`. MuPDF still sees a real and skips the setter. Reparsing that printed dictionary could invent a round dot. Accept finite, nonnegative MuPDF-float widths, including zero, and PDF **integer** caps `0`, `1`, `2`. Treat invalid values conservatively without coercion or clamping. [pdf_object_source.py:116](utils/pdf_object_source.py:116) · [MuPDF 1.27.1 ExtGState dispatch](https://github.com/ArtifexSoftware/mupdf/blob/1.27.1/source/pdf/pdf-interpret.c#L833-L846)
- Give `scan_page` a keyword-only table keyed by decoded PDF name **bytes**, using the scanner’s leading-slash convention and decoding `#xx` exactly once. An empty table preserves today’s bytes-only behavior. Proposed admission includes `/LW`, `/LC`, optional valid `/Type`, and valid nonstroking `/ca`, including the `/ca`-only case already reported for B7. [scan.py:300](model/vector_paths/scan.py:300) · [B7 review:24](plans/b7-review-r1.md:24)

| Lookup at `gs` | Width after `gs` | Cap after `gs` |
|---|---|---|
| Admitted `(lw, lc)` | Set `lw` | Set `lc` |
| Admitted `(lw, None)` or `(None, lc)` | Set if supplied, otherwise keep prior width | Set if supplied, otherwise keep prior cap |
| Admitted `(None, None)`, e.g. valid `/ca` only | Keep prior width, including NaN | Keep prior cap, including NaN |
| Missing name, `/Font` only, malformed field, ambiguous name, broken reference, or unsupported entry | NaN | NaN |

`/LW` is in user space. Apply the CTM and page frame **at stroke time**. MuPDF dispatches `/LW` through `w`, stores the unscaled float, and supplies the current CTM to `fz_stroke_path`. `q/Q` saves and restores the pen. A later `w` or `J` restores knowledge of its own field independently. [ISO 32000-1 §§8.4.3.2, 8.4.5](https://opensource.adobe.com/dc-acrobat-sdk-docs/pdfstandards/PDF32000_2008.pdf) · [MuPDF width setter](https://github.com/ArtifexSoftware/mupdf/blob/1.27.1/source/pdf/pdf-op-run.c#L2307-L2318) · [MuPDF stroke call](https://github.com/ArtifexSoftware/mupdf/blob/1.27.1/source/pdf/pdf-op-run.c#L906-L915)

### 2. Scanner parity and hit testing

- **G** applies the two field updates at `gs`. **F** uses its existing name offsets and emits independent scoped setter events for width and cap. `KEEP` emits no event for that field. An unknown lookup emits a NaN event for each. Pass the same snapshot through F’s whole-page fallback to G. Preserve `PAGE_ANCHORED`, block resource records, and existing edit/move eligibility. [scan.py:705](model/vector_paths/scan.py:705) · [scan.py:790](model/vector_paths/scan.py:790) · [scan_fast.py:710](model/vector_paths/scan_fast.py:710) · [scan_fast.py:768](model/vector_paths/scan_fast.py:768) · [scan.py:1175](model/vector_paths/scan.py:1175)
- Keep `line_width = LW × σmax` for finding **candidates**. It is rounded outward, and the current final distance test also rounds every segment end. For rows gaining hits through this change, retain nominal width and eligibility for widening. Inverse-transform the candidate through the paint CTM composed with the frame. Accept a straight segment’s interior strip only within its longitudinal endpoints. Test a proven mixed-path round dot in user space using its actual radius. A hairline earns no additional page-space radius. Keep the caller’s existing tolerance independent. [scan.py:962](model/vector_paths/scan.py:962) · [scan.py:998](model/vector_paths/scan.py:998) · [scan.py:1076](model/vector_paths/scan.py:1076) · [index.py:235](model/vector_paths/index.py:235) · [index.py:261](model/vector_paths/index.py:261)
- Grant new hits only where the stroke is proved solid and visible. A dash gap, active clip, soft mask, unknown stroking opacity, pattern, unreliable transform, or unproved curve gets the existing conservative behavior. Carry that uncertainty through subsequent partial `gs` updates and restore it on `Q`. A later valid `/LW` cannot establish that an earlier soft mask disappeared. This gate also applies when emitting newly resolved dots, since marquee touch reads the dot table directly. [index.py:184](model/vector_paths/index.py:184) · [scan_fast.py:1241](model/vector_paths/scan_fast.py:1241)

### 3. Source identity and lifetime

- Define source identity as **ordered stream digests + frame + ExtGState digest**. Keep `stream_digests` one-for-one with `/Contents`. Hash the complete admitted table in decoded-name byte order with a version tag, length-prefixed names, explicit `KEEP` tags, normalized float32 widths and integer caps. A known no-op must hash differently from a missing entry. Equivalent xref renumbering should hash identically. Include the composite identity in `VectorSelectionInfo`. [transport.py:173](model/vector_paths/transport.py:173) · [pdf_model.py:4678](model/pdf_model.py:4678)
- A direct `xref_set_key` on a shared state, an ancestor `/Resources` replacement, or a resource-name rebind can change paint with identical `/Contents`. The model revision advances through edit/history bookkeeping. The controller render revision advances through an explicit bump. Neither observes a raw xref write. Capture session, handle, revision and source identity at dispatch. Compare the returned identity to the request and the live page before installation. Revalidate the bounded resource digest on cache use and invalidate the selection on mismatch. Today an asynchronous result can be installed under the revision current **at arrival**. [pdf_model.py:1453](model/pdf_model.py:1453) · [pdf_model.py:4589](model/pdf_model.py:4589) · [pdf_controller.py:1168](controller/pdf_controller.py:1168) · [pdf_controller.py:5317](controller/pdf_controller.py:5317)
- Give `plan_delete` a freshly captured snapshot. Compare its identity with the selected index and rescan the derived streams with that same table. Carry the digest on `VectorPlan`. Under the write lease, compare live resources, selected index and plan immediately before the first write, after any yielding pre-pass. A mismatch returns `VECTOR_SELECTION_STALE` before mutation. Preserve the existing stream, frame and selection-mask checks. [pdf_model.py:4367](model/pdf_model.py:4367) · [edit.py:79](model/vector_paths/edit.py:79) · [edit.py:142](model/vector_paths/edit.py:142) · [commit.py:107](model/vector_paths/commit.py:107) · [commit.py:131](model/vector_paths/commit.py:131)

### 4. Child protocol and limits

- Keep the two payloads and outer object-probe protocol v2. Introduce an explicit **vector job schema 2** in the JSON payload head with `dir`, `frame`, `lengths`, sorted `[name_hex, lw_or_null, lc_or_null]` rows and the digest. The child validates and recomputes the digest. Give `index.npy` metadata an explicit **vector index schema 2**, the digest, and the per-row data needed for the narrow hit test. Keep the NPY envelope at 1.0. Reject missing or unsupported schemas and mismatched digests before install. The in-process worker takes the identical snapshot. [vector_edit_coordinator.py:198](controller/vector_edit_coordinator.py:198) · [vector_edit_coordinator.py:308](controller/vector_edit_coordinator.py:308) · [helper_main.py:113](src/object_probe/helper_main.py:113) · [transport.py:112](model/vector_paths/transport.py:112)
- Proposed limits are 8 page-tree hops, 4 indirect hops per lookup, 4,096 state entries, 127 decoded bytes per name, 1 MiB encoded table and 4 MiB total job head. Bound dictionary enumeration and total resolver work before materializing the table. Check declared head/blob sizes before the child reads them. Reject duplicate decoded names, invalid types, nonfinite numbers and manifest mismatches. Aggregate overflow returns `TOO_LARGE`. Existing limits are 64 KiB for the **outer** header, 100,000 streams, 256 MiB decoded content, 64 MiB output metadata and 512 MiB output payload. [limits.py:9](model/vector_paths/limits.py:9) · [helper_main.py:32](src/object_probe/helper_main.py:32) · [helper_main.py:188](src/object_probe/helper_main.py:188) · [transport.py:50](model/vector_paths/transport.py:50)

### 5. Red-light order and owner decisions

1. Start with a real PDF and zero tolerance. A resolved fat stroke and a mixed round dot must hit sampled ink. The narrow side of an anisotropic dot, a point past a butt end, and a dash gap must miss. Put an editable path underneath the blank probes to catch selection of the wrong parent. [test_vector_dots.py:186](test_scripts/test_vector_dots.py:186)
2. Test direct, indirect, inherited and locally shadowed resources, same-name forms, escaped names, PDF real `/LC 1.0`, `/Font` only, broken references, one-field updates, `w/J`, nested `q/Q` and state across `/Contents` boundaries. [test_vector_page_source.py:48](test_scripts/test_vector_page_source.py:48) · [test_vector_dots.py:49](test_scripts/test_vector_dots.py:49)
3. Extend `_same` to compare **dots**, new pen data and digest byte-for-byte. It currently compares five tables and omits dots. Generate resource tables alongside both admitted and sloppy fuzz programs. Assert actual F admission on supported cases, identical fallback/refusals, and preserved empty-table behavior. [test_vector_scan_fast.py:25](test_scripts/test_vector_scan_fast.py:25) · [test_vector_scan_fast.py:259](test_scripts/test_vector_scan_fast.py:259) · [test_vector_scan_fast.py:597](test_scripts/test_vector_scan_fast.py:597)
4. Exercise the real child, in-process worker and transport round trip. Test old schema, wrong digest, malformed rows and each budget boundary. Mutate only `/LW` or `/LC` during dispatch, after selection and after planning. Require stale refusal, zero writes and no history record. Then delete a different row and verify a surviving `gs` dot after derived-index installation and save/reopen. [test_vector_scan_child.py:311](test_scripts/test_vector_scan_child.py:311) · [test_vector_delete_model.py:126](test_scripts/test_vector_delete_model.py:126) · [test_vector_delete_plan.py:116](test_scripts/test_vector_delete_plan.py:116)

**Owner decisions.** Ratify the initial dictionary allowlist and resource budgets, and whether over-budget pages should refuse or retain bytes-only selection. I recommend starting with the proved straight-stroke and round-dot cases above. Gate expansion and cache revalidation on painted-pixel tests and the existing 50 ms CAD click budget. [B7 performance baseline:30](plans/b7-progress.md:30)

## Evidence

- In-memory PyMuPDF/MuPDF **1.27.1** raster probe, exit 0. At 4× zoom, `/LW 4` measured **16 pixels** at identity and **32 pixels** with a 2× CTM, whether `cm` preceded or followed `gs`. Changing only the resource width from 8 to 2 changed the rendered cross-section from 32 to 8 pixels with the same stream SHA-256.
- G/F query probe, exit 0. With a `4 × 1` CTM, both scanners’ literal-pen equivalent selected a point 4 pt along the dot’s narrow axis. MuPDF rendered it white and rendered the corresponding long-axis point black. Both scanners also selected a white point 2 pt past a butt endpoint.

## Not performed

No edits or pytest runs were requested. The additional live-model cache probe, invoked through `.venv\Scripts\python.exe -B -`, stopped at `PDFModel()` with `PermissionError: [WinError 5] 存取被拒。: '<repo>/pdf_temp'`. The revision and cache findings above come from the working-tree source.

## Fence log

Scope stayed within the B7 `/LW` and `/LC` design. Form descent, general clipping support and move eligibility remain separate owner decisions.

## Verified

Tried to refute paint-time width, the safety of the current circular hit radius, and preservation of `/LC` type through object printing. The raster confirmed paint-time width. The white-pixel hits and real-to-integer printout ruled out both shortcuts.

## Log
- 11-28 design requested and recorded; no code.
