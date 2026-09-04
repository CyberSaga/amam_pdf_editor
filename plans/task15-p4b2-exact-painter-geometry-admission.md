# Task 15 — P4-B2 production slice: exact painter geometry admission (+ two prerequisite correctness fixes)

**Branch:** `task15/p4-b2-exact-painter-geometry-admission`, cut from the spike tip
`17065a3` (`task15/p4-b2-exact-painter-geometry-spike`). No merge, PR or push
unless the user asks. Sealed corpus paths stay CLI-only.

**Planner:** Fable 5.1 (design, gates, sequencing). **Implementers:** Sonnet /
Opus / Codex `gpt-5.6-luna --effort xhigh`, dispatched serially, red-first per
CLAUDE.md §5.1. **Reviews:** Codex `gpt-5.6-sol --effort high`.

**Prerequisite maps (2026-09-04, three serial Opus readers, PyMuPDF 1.27.1
probes in the venv):** the facts below marked MEASURED come from those probes;
the probe scripts were scratchpad-only and are re-created as red tests here.

## 0. Why three slices, and in this order

| Slice | Item | Why it is here |
| --- | --- | --- |
| 1 | Exact transactional stream restore (`AppliedPatch.revert`, undo/redo) | Correctness bug reachable from the live FAILED-verify path; the drift is persisted by `PDFModel._save_doc` (no `deflate`/`clean`, MEASURED). Independent of the gate. |
| 2 | Visual matrix on rotated cropped / UserUnit pages (`transforms.py:203` and four sibling sites) | The duplicate-painter gate places every quad through `map_text_quad_to_visual`; slice 3 must not be built on a chain that is wrong on every rotated cropped page (MEASURED 60×50 pt error on `/Rotate 90` + offset CropBox, UserUnit 1). Also a false-ACCEPT source: `_grown_verify_bbox` under-sizes the growth band by the UserUnit factor on rotated UserUnit pages. |
| 3 | Exact painter geometry admission (the P4-B2 GO) | Replaces the declared-advance ink quad on both sides of the gate for the CID population. |

## 1. Slice 1 — exact stream restore

### 1.1 Facts (MEASURED unless noted)

- `update_stream(xref, decoded, compress=True)` (what `revert` does today) rewrites `/Length`, drops `/Filter` and `/DecodeParms`, and keeps whichever of flate/raw is SMALLER — there is no size threshold. A 57,000 B uncompressed stream comes back as `/Length 181 /Filter /FlateDecode`; a 44 B stream stays bare.
- Through the real `TieredCommitEngine.commit` FAILED branch (`engine.py:274`, injected `VerificationFailure`): Flate, Flate+`/DecodeParms << /Predictor 12 /Columns 4 >>`, and `[/ASCIIHexDecode /FlateDecode]` content streams all come back as `<< /Length 44 >>`; decoded bytes exact; `doc.is_dirty` True in every case, including a byte-identical rewrite.
- `update_stream(xref, raw, compress=False)` restores the raw bytes but strips the dict, so `xref_stream()` then returns the RAW flate bytes. Restoring the dict afterwards with `update_object(xref, original_xref_object_string)` restores all five encodings exactly (raw, object string, decoded). Order is load-bearing: `update_object` then `update_stream` loses the dict (matches PITFALLS "Restore stream bytes before restoring the stream dictionary").
- Whole-object restore also handles indirect `/Length N 0 R` + `/Filter N 0 R`. `xref_get_key` cannot distinguish an absent key from `null`; `xref_set_key(x, 'DecodeParms', 'null')` leaves a literal `/DecodeParms null` entry. So the TODOS per-key design is DROPPED in favour of whole-object restore.
- A wrong `/Filter` is validated nowhere: `xref_stream()` silently returns `b""` (MuPDF prints `zlib error` to stderr, raises nothing), `tobytes()` succeeds, the reopened page extracts as `""`. A mis-restore is silent content loss that saves cleanly.
- `new=` on `update_stream` is inert in 1.27.1. Cost on a 228 KB decoded / 641 B raw Flate stream: `xref_stream_raw` 31.9 µs, `xref_stream` 447.8 µs, `update_stream(compress=False)` 49.9 µs, `update_stream(compress=True)` 2,889 µs — exact restore is a perf win on the preview keystroke path.
- `doc.save(garbage=0, encryption=KEEP)` preserves raw + object byte-identically for all five encodings (save does not re-encode), so the drift reaches the persisted file and an exact restore survives the app's real save path.
- Sites: `patch.py:137-144` (capture/apply loop), `patch.py:84-99` (`revert`), `engine.py:255` (revert inside `except BaseException` — a raising revert escalates to "document may be inconsistent"), `engine.py:274`, `preview.py:343/382` (scratch, `compress=False`), `edit_commands.py:283` (pre_streams capture), `:349-375` (`_capture_tier0_reversal`), `:394` (redo apply), `:460` (undo apply). Three monkeypatch sites pin `revert(self, doc_, *, compress=False)`: `test_text_commit_apply_compress.py:406-407, 590-591`, `scripts/benchmark_p3c_stage_census.py:146-167`.

### 1.2 Design (decided)

- `model/text_commit/inspect.py` gains, next to `capture_annotation_parent_refs` / `restore_annotation_parent_refs`:
  - `@dataclass(frozen=True) class StreamStorage: xref: int; raw: bytes; obj: str; decoded: bytes`
  - `capture_stream_storage(doc, xref) -> StreamStorage` (`xref_stream_raw`, `xref_object`, `xref_stream() or b""`).
  - `restore_stream_storage(doc, storage) -> bool`, in this order and NEVER raising: (0) short-circuit `True` when `xref_stream_raw == raw and xref_object == obj`; (1) `update_stream(xref, raw, compress=False)`; (2) `update_object(xref, obj)`; (3) self-check `xref_stream_raw == raw and xref_object == obj and xref_stream() == decoded`; (4) on mismatch or any exception: `logger.warning`, fall back to `update_stream(xref, decoded, compress=True)` (today's behaviour), return `False`. No `new=` kwarg.
- `AppliedPatch` keeps `page_xref` and `prior_streams` (decoded, unchanged shape for readers) and adds `prior_storage: tuple[StreamStorage, ...]`, captured in the existing per-stream loop in `apply_patchset` before the first mutation. `revert(doc, *, compress=True)` keeps its signature (the kwarg is accepted and ignored, docstring says so) and delegates to `restore_stream_storage` per record.
- Undo/redo (fix the class, not the instance): `EditTextCommand` captures pre-commit storage next to `pre_streams` (`edit_commands.py:283`) and post-commit storage inside `_capture_tier0_reversal`; after the undo apply (`:460`) restore the pre-commit storage; after the redo apply (`:394`) restore the post-commit storage. Docstring states the honest scope: undo is original-fidelity; redo is self-consistent with the commit it replays; a SUCCESSFUL commit still lands as MuPDF's chosen encoding (re-encoding new bytes under the original filter chain is out of scope — TODO).
- Preview scratch path (`preview.py`) unchanged in call shape; the existing pins (`counts == (0, 2)`, raw-length stability over 21 keystrokes) must stay green.
- Multi-stream patchsets: restore best-effort per stream, log, return the AND of results (policy: no cross-stream rollback).

### 1.3 Red tests (write first, show them fail)

New helper `test_scripts/stream_storage_fixtures.py`: a hand-written-xref PDF builder producing a page whose `/Contents` is stored as (a) uncompressed, (b) `/FlateDecode`, (c) Flate + `/DecodeParms << /Predictor 12 /Columns 4 >>` (PNG-Up encoded), (d) `[/ASCIIHexDecode /FlateDecode]`, (e) tiny (≤ 20 B) uncompressed, (f) indirect `/Length N 0 R` + `/Filter N 0 R`, (g) two-stream `/Contents` array with mixed encodings. It must NOT use `update_stream` to install the streams (that is the mechanism under test).

New group in `test_scripts/test_text_commit_apply_compress.py` (or a sibling file `test_text_commit_exact_restore.py`):
1. (a)–(g) × `apply_patchset` + `AppliedPatch.revert`: `xref_stream_raw`, `xref_object`, `xref_stream` byte-identical afterwards.
2. (a)–(d) × real `TieredCommitEngine.commit` with `verify_tier0_commit` monkeypatched to return `VerificationFailure`; and once with a RAISING verifier (exercises `engine.py:255`); status `failed`, storage exact, nothing raises.
3. (a)–(d) × undo and redo through `EditTextCommand` (undo exact vs pre-commit; redo exact vs post-commit snapshot).
4. Corruption negative: patch `update_object` to a no-op → self-check fails → fallback fires, decoded bytes exact, returns `False`, no exception, one WARNING logged.
5. Save + reopen leg on (c): reopened raw and object still match.
6. Premise pins (so a PyMuPDF bump is visible): `update_stream(compress=True)` on a 57 kB uncompressed stream ADDS `/FlateDecode`; `update_object` then `update_stream` loses the dict; wrong `/Filter` → `xref_stream() == b""` without raising.
7. Invert `test_revert_compress_false_does_not_restore_original_storage_encoding` (it pins the defect) and extend `test_apply_then_revert_compress_false_leaves_non_stream_objects_unchanged` to include the content stream's own `xref_object` / `xref_stream_raw`.

### 1.4 Docs

PITFALLS: rewrite "update_stream(compress=False) never restores the original storage encoding" (now history + the smaller-representation rule replaces the size-threshold folklore); cross-reference "Restore stream bytes before restoring the stream dictionary" (now enforced in `model/`); new entry for the silent wrong-`/Filter` measurement. ARCHITECTURE: `inspect.py` storage capture/restore API. TODOS: close the rollback item; add "successful commit re-encoding under the original filter chain" as a new deferred item.

## 2. Slice 2 — page visual frame on rotated pages

### 2.1 Facts (MEASURED, 1.27.1)

- On `/Rotate ≠ 0`, `page.transformation_matrix` collapses to `(1,0,0,-1,0,H_unclipped_crop)`: it drops the CropBox origin AND `/UserUnit`. Independently, `page.rotation_matrix` / `derotation_matrix` (a) always drop `/UserUnit` and (b) use the UNCLIPPED CropBox dims, so they are wrong whenever CropBox ⊄ MediaBox. `rotation_matrix` is right only when CropBox ⊆ MediaBox and UserUnit == 1.
- `map_text_quad_to_visual` (`user × transformation_matrix × rotation_matrix`) misses the pixmap on EVERY rotated cropped page: MediaBox `[0 0 595 842]`, CropBox `[50 60 545 782]`, no UserUnit, `/Rotate 90` → (200,100) vs ink at (140,50).
- The dict→visual path `pdf_text_edit._dict_space_to_visual` (`dict × rotation_matrix`) is right on that shape but wrong whenever UserUnit ≠ 1 or CropBox ⊄ MediaBox: (−362,100) vs ink (280,100). `verify._visual_bbox_to_dict_space` uses `derotation_matrix`; today the two defects cancel in the dict→visual→dict round trip. Fixing one side alone breaks that symmetry — the five sites move together.
- Correct in 32/32 ink-anchored cells (8 shapes × 4 rotations) and 12/12 edge cells (reversed box literals, inherited boxes with page keys nulled, indirect `/UserUnit`, no CropBox): `visual = user × BASE × R(rotation, W0, H0)` with `BASE = (uu, 0, 0, -uu, -uu·clip.x0, uu·clip.y1)`, `clip = raw_cropbox ∩ mediabox`, `raw_cropbox = (cb.x0, mb.y1 - cb.y1, cb.x1, mb.y1 - cb.y0)` (PyMuPDF reports `page.cropbox` y-flipped against `mediabox.y1` and unclipped, constant across rotations), `uu` from `inspect.py:335-345`'s reader, `(W0, H0) = uu·clip dims` (= `page.rect` dims swapped for 90/270), `R(0) = I`, `R(90) = (0,1,-1,0,H0,0)`, `R(180) = (-1,0,0,-1,W0,H0)`, `R(270) = (0,-1,1,0,0,W0)`. At rotation 0, and on any uncropped uu=1 page at every rotation, this is bit-identical to today's chain.
- The `set_rotation(0)` window used by `interpretation.py:105-112` and the spike permanently sets `doc.is_dirty` on a clean document (False → True, never restored). Production geometry must compute, not capture. (`interpret_page` already dirties every rotated-page verify/preview — pre-existing, filed as TODO, not touched here.)
- `visual_baseline_direction` (`transforms.py:136`) is immune (linear part only, uniform positive scale); the census direction numbers are unaffected. `inspect._update_page_geometry:346-354` folds the raw matrices into the fingerprint as a staleness signal — leave it.

### 2.2 Design (decided)

- `transforms.py` becomes the single source: `@dataclass(frozen=True) class PageVisualFrame: base: fitz.Matrix; rotation: int; width0: float; height0: float; user_unit: float` with `.visual` (BASE × R) and `.inverse` (`~visual`), and `page_visual_frame(page) -> PageVisualFrame`. `map_text_quad_to_visual(page, tm, ctm, quad, *, frame: PageVisualFrame | None = None)` — page-derived and correct by default; callers that hold a frame pass it.
- `/UserUnit` semantics: mirror MuPDF. Red test first: for `/UserUnit` absent, `2`, `2.0`, indirect, `0`, negative, non-numeric, measure `page.rect` at rotation 0 against the MediaBox/CropBox dims to learn what MuPDF applies, and implement exactly that (the base matrix is by definition MuPDF's rotation-0 `transformation_matrix`, so at rotation 0 assert `page_visual_frame(page).base == page.transformation_matrix` on every fixture shape — that is the self-check).
- Five sites change in ONE commit: `transforms.py:203`; `plan.py:219-227` (`_page_visual_matrix` → `page_visual_frame(page).visual`, forward and inverted at `:1055/:1066`); `inspect.py:555-571` (`_origin_in_page_space`); `verify.py:197-212` (`_visual_bbox_to_dict_space` → `frame.inverse`, since dict space IS base space); `model/pdf_text_edit.py:1325-1350` (`_dict_space_to_visual` → `R(rotation, W0, H0)` only). Do NOT touch `transforms.py:136` or the fingerprint fold. `model/geometry.py:55-82` (annotation/object/hit-test chokepoints) share the defect but are OUT of this slice → TODO with the measurement.
- Per-prepare caching: compute once where the page is first bound in `_classify_common` and thread the frame through the gate calls (`plan.py:354-356, 418, 480, 914, 1106`); the shadow-census wrapper (`measure_p4b2_shadow_census.py:402`) keeps working through the default.

### 2.3 Red tests

`test_scripts/test_text_commit_visual_frame.py`, fixtures via `painter_matrix_fixtures.set_page_boxes` / `set_user_unit`, every assertion anchored to 72-dpi pixmap ink bounds (never to `rotation_matrix` arithmetic):
- Shapes A (plain, control: bit-identical to today), B (MediaBox (0,0,595,842) + CropBox (50,60,545,782), uu 1), C (no CropBox, uu 2), D (CropBox inside, uu 2), E (MediaBox (−100,−100,495,742) + CropBox (50,60,545,782), uu 1), F (E's boxes, uu 2), G (CropBox (100,100,300,400), uu 0.5), H (CropBox (−20,−30,400,900) vs MediaBox (0,0,595,842), uu 3) × rotations 0/90/180/270. E at 180 is the cell no wrong formula passes — it must be present.
- `map_text_quad_to_visual` of the glyph's text quad contains the ink bbox on every cell; `_origin_in_page_space` lands on the ink corner; dict→visual→dict round trip is identity through the new pair; `_grown_verify_bbox` band width equals `growth_advance × uu × |linear|` on F.
- Premise pins: on F at 90, `page.transformation_matrix != frame.base` and `page.rotation_matrix != R(...)`; `page.cropbox` is reported y-flipped/unclipped (12 edge shapes); a fresh doc stays `is_dirty == False` after `page_visual_frame`.
- Re-point `test_text_commit_trm_admission.py:605-618` and `test_text_commit_structural_gates.py:771-795` at the frame chain.

### 2.4 Docs

PITFALLS `:2794-2799` extended (rotation_matrix half; arithmetic reconstruction; window dirties the doc). ARCHITECTURE: `PageVisualFrame` as the one visual chokepoint. TODOS: audit item closed; new items for `model/geometry.py` chokepoints and for `interpret_page` dirtying.

## 3. Slice 3 — exact painter geometry admission

### 3.1 Facts that revise the spike's premise (MEASURED on the fixture font, upem 256, 50,483 glyphs)

- glyf header boxes equal `fz_bound_glyph` exactly on 300/300 gids and on all sampled composites; but MuPDF **ignores the header**: zeroing a simple glyph's header shifted its bound by `lsb − xMin_new` and left the outline; zeroing a composite's header changed nothing. A stale/zeroed subset header therefore under-bounds silently.
- The spike's 3/3,001 one-unit deltas are FreeType's `(hmtx.lsb − glyf.xMin)` outline translation, not curve flattening (2/4,000 here, both exactly the glyphs with `lsb ≠ xMin`, both +1 in x). "Compute the box from the point array" alone does not fix it; the lsb shift does.
- One font unit exceeds ε = 0.05 pt once `font_size > 0.05·upem` (12.8 pt at upem 256). The pad must be applied, never assumed sub-epsilon.
- Gate facts: the only advance→ink conversion is `_painter_core_quad` (`plan.py:312-337`), used for the target (`:415`) and candidate (`:457-459`); the gate already runs before `page_fingerprint` (`:880` vs `:895`); `source_cids`/`replacement_cids` (`:782-789`, both past `glyph_gate`) and `snapshot.streams` (`:628`) are in scope at the call site; `ShowOp.origin_reliable` is False for any show after another show in the same BT (the replay never advances Tm by a string); TJ kerns must be re-lexed from `stream[string_start:string_end]`; `GlyphProgram` holds only `num_glyphs/loca/glyf_length`; `parse_truetype_glyph_program` already has `head` (≥ 52 B), `maxp`, `loca`, `glyf` in hand and returns `None` for OTTO/CFF; `DocumentFontRegistry` (generation + per-hit digest revalidation) is the natural owner of a `(font_xref, gid)` cache; no import-linter contract names `scripts/`, so the boundary `model/ ↛ scripts/` is honoured by construction (re-home, never import).

### 3.2 Design (decided)

**Population.** The exact arm addresses the CID population: target with `capability.cid` and twins with their own `capability.cid` (a twin's ink is bounded from ITS program — identity is irrelevant to the bound). Simple-font targets/twins keep the existing advance-quad path UNCHANGED in this slice, as a stated residual: removing it would refuse every Latin document whose target word appears twice in the same font, and no measurement backs that regression. (This narrows the spike's "declared advance never an ink bound" ruling to the population it was measured on; a simple-font glyph route — TrueType `cmap`/`Encoding` → gid — is filed as the follow-up.)

**Glyph boxes (`cid_fonts.py` + new `model/text_commit/glyph_boxes.py`).**
- Extend the existing single sfnt pass: `GlyphProgram` gains `units_per_em` (head[18:20]), `index_to_loc_format`, table offsets for `glyf`/`hmtx`/`hhea.numberOfHMetrics`; the program bytes are still not retained on the capability (memory).
- `GlyphBoxCache` (owned by `DocumentFontRegistry`, key `(font_xref, evidence_digest, gid)`, one-slot memo of the last fetched program bytes so a prepare fetches each font once; fetch via the descriptor walk in `build_identity_h_cid_capability:950-965`, never `extract_font`). Value: `GlyphBox(units: Rect, reason: str | None)`.
- `glyph_unit_box(program_bytes, gid)`: **point-verified**, not header-trusted. Simple glyph: parse flags/x/y, take the min/max of the on-curve AND off-curve points (control box = FreeType's `cbox` = `fz_bound_glyph`), then shift x by `(lsb − xMin_header)` where lsb comes from `hmtx` (or the last metric for gids ≥ numberOfHMetrics), then pad by 1 font unit on every side. Composite: walk components (`ARGS_ARE_XY_VALUES` required — point-matching args → `ambiguous`; `WE_HAVE_A_SCALE` / `X_AND_Y_SCALE` / `TWO_BY_TWO` applied; `SCALED_COMPONENT_OFFSET` honoured; depth ≤ 8, cycles → ambiguous), transform each component's point box by its 2×2 (AABB of the four transformed corners) plus offset, union, pad 1 unit. Header cross-check: if the header box and the point box differ by more than 1 unit on any side → `ambiguous` (`glyf_header_disagrees`); zero-area point box on a glyph with data → `ambiguous`. Any parse error → `ambiguous` with a closed slug. Slugs: `glyf_unavailable` (OTTO/CFF/no program), `glyf_parse_error`, `glyf_header_disagrees`, `composite_unsupported`, `gid_out_of_range`.

**Placement.** Re-home the pure arithmetic from `scripts/painter_geometry.py:70-193` (`matrix_concat`, `transform_rect`, `scale_units_to_text`, `rect_union`) and from `scripts/painter_evidence.py` (`tj_items:306-345`, `predict_glyphs:366-418`) into `glyph_boxes.py` by copying — no `scripts/` import, no fontTools, no fitz devices. Per glyph: units → text space `[Tfs·Th, 0, 0, Tfs, 0, 0] / upem`, translate by `(cursor_x, rise)`, then `map_text_quad_to_visual(page, show.tm, show.ctm, quad, frame=frame)` (slice 2's chokepoint; hscale enters once in the unit→text scale; shear/rotation via the four-corner transform, no extra pad).

**Cursor replay.** Identity-H only: `x += (w/1000·Tfs + Tc)·Th`, no Tw; TJ kerns `x −= n/1000·Tfs·Th` from the re-lex; `gid_for(cid)`. Requires `origin_reliable`; otherwise `ambiguous` (`origin_unreliable`). Re-lex failure → `ambiguous` (`tj_relex_failed`).

**Gate (`plan.py`).** `duplicate_source_painter_detail` gains keyword-only `streams: Mapping[int, bytes] | None = None`, `replacement_cids: tuple[int, ...] | None = None`, `glyph_boxes: GlyphBoxCache | None = None`, `frame: PageVisualFrame | None = None`; the call site passes `snapshot.streams`, `replacement_cids`, the registry's cache and the prepare's frame. Exact-first composition, per twin, in this order:
1. `capability.cid is None` on target or twin → this twin goes to the EXISTING path (unchanged strings and behaviour).
2. Twin `render_mode != 0` → `ambiguous` (`non_fill_render_mode`) → existing reach path.
3. Target ink = union over `source_cids` ∪ `replacement_cids` boxes, placed by the target's own replay (rise 0, mode 0 already enforced). Any target glyph `ambiguous`/unavailable → keep today's target failure string (`cannot prove target placement`).
4. Twin ink = per-glyph boxes from the twin's own capability and replay. Any glyph ambiguous → reach path (`unproven = "exact extent"` semantics preserved).
5. Aggregate AABB prefilter (strict overlap depth ≤ 0.05 on either axis → `exact_safe`); else every (target glyph, twin glyph) pair with `_strict_overlap_depths`; any pair > 0.05 on both axes → REFUSE with a new detail string: `"identical source painter's glyph ink overlaps the target ink by {x:.3f}pt x {y:.3f}pt"` (same-baseline and cross-baseline both refuse — strict reading; the hazard-model reading is reported by the census only).
6. `exact_safe` → continue to the next twin. Existing five refusal strings stay verbatim for the paths that still use them.
`_painter_advance` keeps its symbol and `None` contract (the shadow census stubs it for the reach arm); `_painter_core_quad(show, 0.0)` still provides the reach baseline band.

**Caching / ordering.** Unit boxes are document-lifetime on the registry; placed quads are per prepare only. Evidence is built before `page_fingerprint` (already true at the call site). No new `fitz` device on the production path.

### 3.3 Red tests

- `test_scripts/test_glyph_boxes.py`: fixture font (`fontfile2_xref`) — for 300 simple + 30 composite gids the padded point box ⊇ `mupdf.fz_bound_glyph(font, gid, fz_scale(upem, upem))` and ⊆ it ⊕ 1 unit; the two `lsb ≠ xMin` gids covered exactly; a zeroed header (probe-2 mutation as a fixture) → `glyf_header_disagrees`, never a box; composite with 2×2 scale and `SCALED_COMPONENT_OFFSET` (synthesised glyf bytes) hand-checked; OTTO → `glyf_unavailable`; gid ≥ numGlyphs → `gid_out_of_range`; cycle → `composite_unsupported`; upem 2048 fixture (`build_face_fixture`); cache key invalidates on font-program rewrite (`bump_generation`/digest).
- `test_scripts/test_p4b2_admission_gate.py` (reuse `_build_second_show_doc`, `_plan_with_second_show`, `painter_matrix_fixtures`, raster oracles): (a) the 8 `/W` cases and the two core-band cases (`second_dy = ±7.3`) now REJECT with the glyph-ink string — flip `test_p4b2_production_pins.py`'s strict-xfail twins to plain passes and delete the characterization pins with a note; (b) value case `second_clone_width=1500` (wide declared `/W`, narrow glyphs) is now ADMITTED where the advance quad refused; (c) TJ twin with a leading kern (`replace_show_with_tj`) is cursor-replayed, admitted when disjoint, refused when overlapping; (d) `Tr 1/2/7` twins fall to reach; (e) simple-font metric clone (`_simple_metric_clone_plan`) unchanged; (f) target with an unreliable origin keeps today's failure string; (g) `Tz 50/150`, `Ts ±`, rotate 90/270 with offset CropBox (slice 2 frame) and a 45° `Tm` all raster-verified: never `exact_safe` when single-painter rasters overlap; (h) the 62-shape falsification matrix (`test_p4b2_falsification_matrix.py`) re-run with the PRODUCTION gate as a fourth arm: 0 false-safes.
- Layer/import guard test: `model/text_commit/glyph_boxes.py` imports nothing from `scripts/` or `fontTools` (AST check, like the existing threading grep).

### 3.4 Census re-validation arm (measurement-only, manual sealed run)

`scripts/measure_p4b2_shadow_census.py`: update the gate wrapper for the new kwargs; add the `production` arm (the real gate with real kwargs) beside baseline/reach/exact; for every row the production arm decides, assert per glyph that the padded glyf box (in derotated space) ⊇ the O1 device box from the spike evidence — counters `glyf_box_contains_o1`, `glyf_box_violation` (must be 0), `glyf_ambiguous.<slug>`, and the production-vs-exact verdict agreement matrix. Sealed constants and identities unchanged. Report `composed_all_gates_pass` under the production arm alongside the spike's 6,618.

### 3.5 Perf (measurement-only)

`scripts/benchmark_p4b2_admission.py`: cold/warm p50/p95/p99 of `prepare_plan` on the two-painter fixture and a dense same-bytes bucket (275 twins) with and without the glyph cache warm; glyph-box parse cost per font on the fixture program; the per-keystroke preview path must not regress beyond noise (compare against `benchmark_p3c_postprepare_latency.py` numbers).

### 3.6 Gates

- Safety: 0 exact false-safes on the matrix and on (g); `glyf_box_violation == 0` on the sealed run; every ambiguous slug falls to reach; no simple-font behaviour change (existing gate tests green unchanged).
- Value: production-arm `composed_all_gates_pass ≥ 5,962` (spike GO threshold), reported against the spike's 6,618; the 187 refused rows re-partitioned.
- Perf: warm prepare within 2× of pre-slice p95 on the dense bucket; first-touch parse per font stated.
- Privacy: census output closed keys, ASCII only (existing test extended).

## 4. Commit sequence

0. `docs: plan the P4-B2 admission slice and its two prerequisite fixes` (this file; TODOS pointers).
1. `fix(text_commit): exact stream storage restore on revert and undo/redo` (slice 1, red logs in §5).
2. `fix(text_commit): page visual frame on rotated cropped and UserUnit pages` (slice 2).
3. `feat(text_commit): point-verified glyph boxes from the embedded program` (slice 3a).
4. `feat(text_commit): exact painter geometry in the duplicate-painter gate` (slice 3b, pins flipped).
5. `feat(census): production arm and glyf-box re-validation in the shadow census` + sealed run entry (slice 3c, measurement-only run).
6. `perf: P4-B2 admission benchmark` (measurement-only).
7. Closing docs (PITFALLS ≥ 6 entries, ARCHITECTURE, TODOS, memory), plan → `plans/archive/`.

Each commit: `.venv\Scripts\python.exe -m pytest` green (3,000+ baseline), `ruff check .` clean, `.venv\Scripts\python.exe -m mypy model/ utils/` untouched-clean; a Codex `gpt-5.6-sol --effort high` adversarial review after commit 2 and after commit 5, findings triaged here.

## 5. Logbook

(red logs, decisions and dead ends are appended per commit)

### Commit 1 — exact stream storage restore

**Red (pre-implementation tree, `.venv\Scripts\python.exe -m pytest
test_scripts/test_text_commit_exact_restore.py -x -q` and a `-k` run over
the two rewritten `test_text_commit_apply_compress.py` cases):**

```
ERROR collecting test_scripts/test_text_commit_exact_restore.py
ImportError: cannot import name 'capture_stream_storage' from
'model.text_commit.inspect'
1 error in 0.37s

FAILED test_apply_then_revert_compress_false_leaves_non_stream_objects_unchanged
  AssertionError: assert before == after
  content_raw differs (still Flate-compressed padded stream vs. the
  compress=False literal write); content_obj differs (/Filter present vs.
  absent)
FAILED test_revert_restores_original_storage_encoding_exactly
  AssertionError: assert applied.revert(doc, compress=False) is True
  AssertionError: assert None is True
    where None = revert(...)  # pre-slice revert() returns None, not bool
2 failed, 27 deselected in 0.76s
```

(the import error was captured with implementation code stashed via `git
stash push -- model/edit_commands.py model/text_commit/inspect.py
model/text_commit/patch.py`, popped immediately after this red confirmation
— test_scripts/ files were untouched by the stash).

**Green:** all 28 new tests in `test_text_commit_exact_restore.py` pass; all
29 tests in `test_text_commit_apply_compress.py` pass (2 rewritten per
section 1.3 item 7, 2 more updated per the deviation below);
`test_text_commit_boundaries.py` / `test_text_commit_tier0.py` /
`test_text_commit_tier1_slice1.py` / `test_text_commit_fingerprint_roundtrip.py`
/ `test_text_commit_preview_contract.py` (69 tests) unaffected.

**Deviation from the plan (measured, not guessed):** section 1.2 promised
the preview scratch path's existing pins stay green "unchanged in call
shape." True for the SHIPPED leg (`compress=False` on both apply and
revert): `counts == (0, 2)` stays exactly as pinned, because
`restore_stream_storage`'s primary write is unconditionally
`compress=False` regardless of the caller's `compress` argument — the same
as before for that leg. NOT true for the "forced `compress=True`" CONTROL
leg six tests in that file use to prove their monkeypatch actually engaged
(`test_preview_renderer_output_identical_between_compress_true_and_false`
and `_assert_class_case_identical_and_uncompressed`'s five callers): since
`AppliedPatch.revert`'s own `compress` kwarg is now ignored, forcing it to
`True` no longer changes revert's own call shape (still one
`compress=False` write from the exact-restore's primary step) — only
`apply_patchset`'s forced `compress=True` splice write does. Measured:
the control leg's call-count signature is `(1, 1)`, not the old `(2, 0)`.
Updated both assertions (with an explanatory comment) rather than the
`(0, 2)` shipped-leg pin, which is unaffected and unchanged; the
byte-identity assertions the counts merely bridge to (`plan_token`,
`png_bytes` equality between shipped and control) still hold and were
re-verified green.

**Measured before/after `xref_object` strings** (cases b–d,
`apply_patchset` full-stream identity-content patch + `AppliedPatch.revert`
on the hand-written fixtures; `applied.revert(doc) is True` in every case,
`before_obj == after_obj` byte-for-byte):

```
case b (Flate):
  BEFORE = '<<\n  /Length 78\n  /Filter /FlateDecode\n>>'
  MID (post-apply, pre-revert) = '<<\n  /Length 78\n>>'
  AFTER  = '<<\n  /Length 78\n  /Filter /FlateDecode\n>>'

case c (Flate + Predictor 12 / Columns 4):
  BEFORE = '<<\n  /Length 111\n  /Filter /FlateDecode\n  /DecodeParms <<\n    /Predictor 12\n    /Columns 4\n  >>\n>>'
  MID    = '<<\n  /Length 80\n  /Filter /FlateDecode\n  /DecodeParms <<\n    /Predictor 12\n    /Columns 4\n  >>\n>>'
  AFTER  = '<<\n  /Length 111\n  /Filter /FlateDecode\n  /DecodeParms <<\n    /Predictor 12\n    /Columns 4\n  >>\n>>'

case d ([/ASCIIHexDecode /FlateDecode]):
  BEFORE = '<<\n  /Length 157\n  /Filter [ /ASCIIHexDecode /FlateDecode ]\n>>'
  MID    = '<<\n  /Length 78\n>>'
  AFTER  = '<<\n  /Length 157\n  /Filter [ /ASCIIHexDecode /FlateDecode ]\n>>'
```

Side finding (not a defect, recorded so a future reader doesn't re-derive
it): the transient MID state on case (c) keeps the ORIGINAL
`/DecodeParms << /Predictor 12 /Columns 4 >>` in the object dict even
though `apply_patchset`'s own `update_stream(new_bytes, compress=True)`
call is a generic splice, not a predictor-aware re-encode — measured that
`doc.xref_stream(xref)` at that MID point still decodes correctly (MuPDF's
`update_stream(compress=True)` is filter-chain-aware when the object
already declares one). No action needed; exact-restore's own
`update_stream(raw, compress=False)` + `update_object(obj)` pair replaces
this MID state entirely on revert regardless.

**Review-round hardening (same commit, caught before commit via an
advisor pass on the finished slice):** `_capture_tier0_reversal`'s
post-commit `capture_stream_storage` loop had no exception guard at all,
unlike the sibling pre-commit capture in `execute()` — a raise there
would have escaped a SUCCESSFUL `execute()` as an uncaught exception.
Fixed red-first (temporarily stripped the guard, confirmed a
monkeypatched `RuntimeError` propagated out of `command_manager.execute`,
reapplied the guard, confirmed green) with
`test_capture_tier0_reversal_post_storage_capture_never_raises`. Doing
this surfaced a second, pre-existing gap in the SAME area: the
pre-commit capture's `except (AttributeError, IndexError, ValueError,
TypeError)` tuple predates `capture_stream_storage` being added to that
block and does not cover what PyMuPDF's `xref_*` accessors actually
raise (`RuntimeError` / `fitz.mupdf.FzErrorBase` — confirmed by the same
red run: the injected `RuntimeError` sailed through that tuple
uncaught). Widened both capture sites' exception tuples to match the
established pattern already used everywhere else in
`model/text_commit/` (`fonts.py`, `cid_fonts.py`, `inspect.py`). See
`docs/PITFALLS.md` "A best-effort capture around fitz xref_* calls must
catch RuntimeError/FzErrorBase too". 29 tests now pass in
`test_text_commit_exact_restore.py` (28 → 29).

### Commit 2 — page visual frame on rotated pages

**Red, stage 1 (nothing implemented) —
`.venv\Scripts\python.exe -m pytest test_scripts/test_text_commit_visual_frame.py -x -q`:**

```
ERROR collecting test_scripts/test_text_commit_visual_frame.py
ImportError: cannot import name 'page_visual_frame' from
'model.text_commit.transforms'
1 error in 0.39s
```

**Red, stage 2 (frame API landed, the five sites still on
`transformation_matrix × rotation_matrix`) — the informative red:**

```
FAILED ...::test_visual_quad_covers_the_rendered_ink[B@90]
E   AssertionError: ((695.8, 72.0, 712.0, 120.0), (639, 22, 650, 69))
E   assert 695.8 <= (639 + 1.0)
...
     21 FAILED ...::test_visual_quad_covers_the_rendered_ink
     20 FAILED ...::test_origin_in_page_space_lands_on_the_ink
     18 FAILED ...::test_dict_visual_round_trip_is_identity_and_lands_on_the_ink
      3 FAILED ...::test_grown_verify_band_carries_the_user_unit
      1 FAILED ...::test_shape_e_at_180_is_the_discriminating_cell
      1 FAILED ...::test_page_visual_frame_never_dirties_the_document
      1 FAILED ...::test_map_text_quad_to_visual_accepts_a_precomputed_frame
65 failed, 65 passed in 1.32s
```

The 21 failing quad cells are exactly the 21 of 32 the probe predicted:
every cell EXCEPT rotation 0 (7 shapes) and shape A (plain page) at all
four rotations, where the two chains are bit-identical.  Green after the
five sites moved: 130 passed.

The two re-pointed regression tests
(`test_text_commit_trm_admission.py::test_map_text_quad_to_visual_folds_the_page_rotation`,
`test_text_commit_structural_gates.py::test_fallback_target_bbox_follows_page_rotate`)
were NOT red for this change and could not be: both run on uncropped
`/UserUnit`-1 pages, the one shape where the legacy chain is correct.
They are re-anchored at the frame and now assert that agreement as an
explicit premise; the new coverage is all in the new file.

**32-cell result (8 shapes × 4 rotations, ink-anchored at 72 dpi):
32/32 pass on the frame chain, 11/32 on the legacy chain** (the 11 are
every shape at rotation 0, plus A at 90/180/270).

**MEASURED `/UserUnit` semantics (1.27.1) — the plan asked for this
first, and the answer changed the design:** MuPDF applies any PDF
*number* verbatim, with no clamp: `2` / `2.0` / an indirect `2` all give
2; `0` collapses `page.rect` to `(0,0,0,0)` and `transformation_matrix`
to all-zero; `-2` MIRRORS the page, giving `(-2,0,0,2,1190,0)` on a
595×842 page.  Every non-number reads as 1: absent, `/Foo`, `(2)`,
`true`, `[2]`, and `1e30` — exponent notation is not PDF number syntax,
so MuPDF's lexer refuses the whole key and `xref_get_key` reports
`('null','null')`.  One indirect hop is resolved and the target judged
the same way (`5 0 R` → `(2)` is 1, not 2).

**Deviations from §2.2, all measurement-driven:**

1. *The base translation is normalized, not `(-uu·clip.x0, uu·clip.y1)`.*
   That closed form is right for `uu > 0` but wrong for the negative and
   zero user units MuPDF actually applies: at `uu = -2` on
   MediaBox `[0 0 595 842]` + CropBox `[50 60 545 782]`, MuPDF returns
   `(-2,0,0,2,1090,-120)`.  Implemented as "translate so the mapped
   clip's MINIMUM corner sits at the origin", which reduces to the
   plan's form for every positive `uu` and reproduces MuPDF exactly for
   `0`, `-2` and `-2.5` (pinned at rotation 0 for all four rotations of
   a cropped page).
2. *`verify._visual_bbox_to_dict_space` uses `~frame.quarter_turn`, not
   `frame.inverse`.*  §2.2 says "`frame.inverse`, since dict space IS
   base space" — but if dict space is base space then visual→dict is the
   inverse of the `/Rotate` term ALONE, not of `base × R`.  MEASURED:
   `get_text('dict')`'s span `origin` is bit-identical at 0/90/180/270
   and equals the user-space origin through `base` on all of A/F/G/H —
   so dict space is base space, and `~quarter_turn` is the conversion.
   `frame.inverse` (= `~visual`) is kept and is what
   `_grown_verify_bbox` rides to reach USER space.  Also noted:
   `dict["width"]`/`["height"]` are the UNSCALED clip dims even when the
   coordinates carry `/UserUnit`.
3. *`read_user_unit` gates on the key KIND before converting.*  A PDF
   string `(2)` reports as `('string', '2')`, which `float()` parses
   happily while MuPDF uses 1 — so kind-gating plus a PDF-number regex
   (no exponents) is required, not optional.
4. *`transforms.py` now imports `fitz` at runtime* (it was TYPE_CHECKING
   only).  No contract forbade it; `model/` may import fitz, and the
   frame needs `fitz.Matrix`/`fitz.Rect`.
5. *No shared `/UserUnit` reader with `inspect.py`.*  §2.2 allowed a
   refactor "if needed"; it is not.  `inspect._update_page_geometry`
   deliberately folds the raw `kind:value` pair for non-numbers (an
   identity signal), the frame needs a float, and `inspect` imports
   `transforms` — so the dependency could only run the wrong way.
   `inspect.py`'s fold is untouched, as §2.2 requires.

**`model/geometry.py` measurement for its TODO item** (`/Rotate 90`,
MediaBox `[-100 -100 495 742]` + CropBox `[50 60 545 782]`): at
`/UserUnit 1` `page.rotation_matrix` is `e = 722` against the frame's
`682` — a displayed point lands **40 pt** off, purely from the unclipped
CropBox; the same boxes at `/UserUnit 2` land **642 pt** off.  Pages with
CropBox ⊆ MediaBox and `/UserUnit 1` are unaffected, which is why the
defect has never been reported.

**`interpret_page` dirtying, confirmed (not just quoted):** on a fresh
`/Rotate 90` document `is_dirty` is `False`; `set_rotation(0)` flips it
to `True`; `set_rotation(90)` restores the rotation but NOT the flag.
Filed as its own TODO — and it is the reason the frame is computed
rather than captured.

**Full-suite finding: the new file was order-dependent.**  Isolated it
was 130 green, but the first full run failed
`test_dict_visual_round_trip_is_identity_and_lands_on_the_ink[H@0..270]`
(4 of 3,464).  Cause is the already-documented process-global flag, not
the frame: `PDFModel.__init__` flips `fitz.TOOLS.set_small_glyph_heights`
to `True` in the first collected test, after which MuPDF reports a tight
fontsize-tall span bbox that sits INSIDE the rendered ink — on shape H
(`/UserUnit 3`) the sub-point difference is magnified to 1.3 visual pt
and the 1 pt ink-containment oracle rejects it.  Reproduced
deterministically by presetting the flag; MEASURED on shape H at
rotation 0 the span bbox y-extent moves `388.488 → 397.299` with the
flag on while `x0` and the origin are untouched (at 270 that y edge
becomes the visual `x0`, which is the edge that failed).  Fixed in the
test file only: an autouse fixture pins the flag OFF (save/restore) so
the ink oracle is valid, and a new
`test_dict_visual_round_trip_is_flag_independent` re-checks the
dict↔visual pair over all 32 cells with the flag ON — the app's own
configuration — so the mapping keeps production coverage.  No production
code changed; 131 green isolated AND with the flag pre-polluted.

### Review round (sol) — commits 1 and 2

Codex `gpt-5.6-sol --effort high` adversarial review of `9d6640e` (slice 1)
and `b912a65` (slice 2), 2026-09-04.  Four findings, all closed in one
commit.  Two of them turned out to be about DOCUMENTED CLAIMS rather than
code, and one grew: the F2 probe found a MuPDF trap the finding did not
know about.

**F1 [high] — indirect `/Length` is lost on save. VALID as a wording
defect; no production change.**  MEASURED: MuPDF's serializer rewrites an
indirect `/Length N 0 R` to a direct integer on ANY non-incremental save,
INCLUDING a save of a document nothing ever touched (case (f):
`<< /Length 6 0 R /Filter 7 0 R >>` becomes `<< /Length 78 /Filter 7 0 R >>`).
An indirect `/Filter` is NOT normalised, and raw + decoded bytes survive
byte-identically.  The correct invariant — (restore, save, reopen) ==
(never touched, save, reopen) — already holds 7/7 for encodings (a)-(g),
so the restore was right and the docstrings were wrong.  Narrowed
`StreamStorage` ("exact IN-MEMORY storage"), ARCHITECTURE, and PITFALLS
(new entry, plus a scope correction on the slice-1 entry).

**F2 [high] — degenerate page boxes. VALID, and the fix is wider than the
finding.**  `page_visual_frame` now proves itself and raises
`transforms.UnsupportedPageGeometryError`;
`RejectReason.PAGE_GEOMETRY_UNSUPPORTED` is emitted by
`plan._classify_common` before any geometry is read.  Three of the
finding's asserted facts were wrong when measured, and following them
literally would have BROKEN working pages:

- *zero-area `/MediaBox`* is not degenerate: MuPDF substitutes Letter AT
  THE BOX READER (`page.mediabox` itself reads `(0,0,612,792)`), the frame
  agrees with `page.rect`, and the page RENDERS ink at `(72,82,119,93)`.
  Admitted, with an ink-anchored test.  Same for a zero-WIDTH MediaBox.
- *`/MediaBox` larger than 10,000 pt* is not clamped — measured at 20,000
  and at 1,000,000.  Nothing to mirror, nothing to reject; the page-box
  check is relative, not absolute, because of it.
- *`/Rotate 45` normalises to 0* — it does for `page.rotation`, but NOT
  for rendering.  MEASURED: MuPDF renders at the NEAREST quarter turn
  (45..134 to 90, 135..224 to 180, 225..314 to 270, 315..44 to 0, and
  `90.5` to 90) while `page.rotation` AND `page.rotation_matrix` report 0
  for every such value.  `/Rotate 135` puts ink at exactly `/Rotate 180`'s
  coordinates with an identity `rotation_matrix` — and since that band
  does not swap the page box, the finding's page-box self-check cannot see
  it either.  `/Rotate` is inheritable and an inherited `135` reproduces
  it.  Added `read_rotate_literal` (page dict, then a bounded `/Parent`
  walk) and refuse anything that is not an exact multiple of 90.  This is
  the most dangerous shape in the whole review: silent 180-degree
  misplacement with every accessor agreeing the page is upright.

  Mirroring MuPDF's fallback instead of refusing was considered and
  rejected on evidence, not taste: the disjoint / edge-touching CropBox
  shapes render NO INK AT ALL, so a mirrored frame could not be validated
  against the ink oracle every other cell in the suite is anchored on.
  Mirroring is untestable there, not merely riskier.

**F3 [medium] — `visual_baseline_direction` still read the page matrices.
VALID.**  Routed through `PageVisualFrame` with an optional `frame=`
kwarg, and `admission_verdict` threads the per-prepare frame from
`_classify_common`.  Results are bit-identical for every positive
`/UserUnit` (the two chains differ only by a positive uniform scale), so
the census direction numbers do not move — MEASURED 32/32 agreement
against a renderer-derived oracle (one glyph vs four at the same authored
origin; the ink edge that moves is the baseline direction) on shapes A-H
at 0/90/180/270.  Neither `scripts/trm_taxonomy.py` nor
`scripts/measure_type0_funnel.py` needed a change (the kwarg is
keyword-only with a default).

**F4 [medium] — `restore_stream_storage` swallowed only `Exception` while
`engine.commit` reverts inside `except BaseException`. VALID.**  A
`KeyboardInterrupt` between the two writes left the stream holding
still-ENCODED bytes under a dictionary with no `/Filter` — silent content
loss that saves cleanly, past BOTH handlers.  Now: `BaseException` gets
the same decoded-bytes fallback write and one WARNING, then is RE-RAISED;
ordinary `Exception` keeps swallowing and returning `False`.
`engine.py`'s boundary semantics are unchanged (a comment records why its
"may be inconsistent" wording no longer applies to that path);
`AppliedPatch.revert`'s "never raises" docstring is corrected.

**Red (pre-implementation), F1 naive form + F4 —
`.venv\Scripts\python.exe -m pytest test_scripts/test_text_commit_exact_restore.py -q -k ...`:**

```
FAILED ...::test_save_reopen_matches_a_never_edited_document_for_every_encoding[f]
E   AssertionError: assert restored == original
E     At index 0 diff: ... '<<\n  /Length 78\n  /Filter 7 0 R\n>>'
E                        != ... '<<\n  /Length 6 0 R\n  /Filter 7 0 R\n>>'
FAILED ...::test_base_exception_mid_restore_still_writes_the_decoded_fallback
FAILED ...::test_base_exception_from_the_first_write_also_falls_back_and_reraises
FAILED ...::test_engine_revert_interrupted_mid_restore_leaves_decoded_bytes_exact[b]
FAILED ...::test_engine_revert_interrupted_mid_restore_leaves_decoded_bytes_exact[c]
FAILED ...::test_engine_revert_interrupted_mid_restore_leaves_decoded_bytes_exact[d]
E   AssertionError: assert b'x\x9c\x01d\...' == b'BT /F1 12 T...ays) Tj ET   '
E     At index 0 diff: b'x' != b'B'
6 failed, 9 passed, 28 deselected in 1.40s
```

The F1 leg was captured in its NAIVE form on purpose — asserting the
promise the docstrings actually made ("restore, then save, yields the
original capture") — because that is the assertion the finding disputes;
it was then replaced by the two-legged invariant.  `[a]` passes the engine
cell honestly: an uncompressed stream's raw bytes ARE its decoded bytes,
so the half-finished restore leaves them correct.

**Red (pre-implementation), F2 + F3, stage 1 —
`.venv\Scripts\python.exe -m pytest test_scripts/test_text_commit_page_geometry_gate.py -x -q`:**

```
ERROR collecting test_scripts/test_text_commit_page_geometry_gate.py
ImportError: cannot import name 'UnsupportedPageGeometryError' from
'model.text_commit.transforms'
1 error in 0.52s
```

(the same import error collected `test_text_commit_visual_frame.py`, which
carries the F3 cells.)

**Red, stage 2 (exception class, `RejectReason` and the frame's self-check
landed; no consumer adapted yet) — the informative red:**

```
FAILED ...::test_non_quarter_turn_rotate_normalises_to_zero
     20 FAILED ...::test_prepare_plan_rejects_unprovable_page_geometry
      1 FAILED ...::test_bind_source_text_fails_closed_on_unprovable_geometry
      1 FAILED ...::test_origin_in_page_space_returns_none_instead_of_raising
      1 FAILED ...::test_dict_space_to_visual_returns_none_instead_of_raising
      1 FAILED ...::test_verify_fails_closed_when_the_frame_stops_being_provable
        E   AssertionError: assert 'verification_failed' == 'page_geometry_unsupported'
25 failed, 41 passed in 2.10s
```

`test_non_quarter_turn_rotate_normalises_to_zero` is the test the
measurement killed: it was written from the finding's premise, failed
against the new gate, and the probe behind that failure is what uncovered
the `/Rotate` rounding trap.  Rewritten as
`test_non_quarter_turn_rotate_is_refused` +
`test_rotate_135_renders_upside_down_while_the_accessors_say_upright`
(ink-anchored) + `test_inherited_rotate_is_read_from_the_page_tree`.

**Red (pre-implementation), F2 second pass — the tier-1 growth-gate hole
found by re-checking the "one chokepoint" claim against the call graph
(`.venv\Scripts\python.exe -m pytest test_scripts/test_text_commit_page_geometry_gate.py -x -q -k tier1_growth_gates`):**

```
>           result = verify_module.verify_tier1_commit(doc, page, grown, pre_state)
model\text_commit\verify.py:1339: in verify_tier1_commit
    probe_failure = _growth_probe_failure(
model\text_commit\verify.py:1143: in _growth_probe_failure
    occupancy = _occupancy_failure(page, doc, growth_rect, regions[0])
model\text_commit\verify.py:1102: in _occupancy_failure
    drawings_overlap = _drawings_intersect_growth(page, growth_rect)
model\text_commit\verify.py:1049: in _drawings_intersect_growth
    growth_dict = _growth_rect_in_dict_space(page, growth_rect)
model\text_commit\verify.py:1037: in _growth_rect_in_dict_space
    _visual_bbox_to_dict_space(
model\text_commit\verify.py:220: in _visual_bbox_to_dict_space
    derotation = ~page_visual_frame(page).quarter_turn
E       model.text_commit.transforms.UnsupportedPageGeometryError: injected by test
1 failed, 74 deselected in 0.64s
```

The traceback IS the finding: seven frames from the tier-1 entry point to
the raise, none of them the gate.  Closed by hoisting the proof into
`verify_tier1_commit`; see deviation 4.

**Deviations from the finding, all measurement-driven:**

1. *No production change for F1* (the finding allowed for this): the
   invariant already held; the wording did not.
2. *Three of F2's rejection shapes are ADMITTED* (zero-area MediaBox,
   zero-width MediaBox, huge MediaBox) — see above.
3. *One rejection class F2 did not list is REFUSED* (non-quarter-turn
   `/Rotate`, inheritance included), and it is the one the finding's own
   proposed self-check could not have caught.
4. *`verify._visual_bbox_to_dict_space` is NOT the guard site.*  F2 asked
   for it to "fail closed"; a coordinate conversion has no fail-closed
   return value, and it has five call sites with five different shapes.
   The guard lives at the gate each public entry point passes through and
   returns the layer's existing `VerificationFailure`.

   *Correction, second pass:* the first pass put that guard only at
   `_verify_patch_postconditions` and called it "the one chokepoint both
   tiers funnel through".  It is not.  `verify_tier1_commit` runs its two
   growth gates FIRST, and `_growth_probe_failure` → `_occupancy_failure`
   → `_growth_rect_in_dict_space` → `_visual_bbox_to_dict_space` converts
   the growth band while the frame is still unproven — so on an ink-growth
   commit an unprovable frame raised straight past the later gate and out
   through `TieredCommitEngine.commit`'s `except BaseException` boundary,
   which is precisely the escape F2 asked to close.  The proof is now
   hoisted to the top of `verify_tier1_commit` as well, and the
   `_verify_patch_postconditions` docstring no longer claims to be the
   single chokepoint.  Tier 0 was always covered (it delegates directly).

   The other three adapters were then re-checked the same way — by walking
   the call graph from the entry point to the first geometry read, not by
   reading the comment above the gate — and both are genuinely clean:
   `inspect.bind_source_text` proves the frame before any geometry (the
   stream read, replay, latin-1 encode and `_cid_show_candidates` that run
   ahead of it touch no coordinates at all), and `plan._classify_common`
   proves it at the last cheap gate, ahead of `resolve_replay` and of
   every `frame=`-threaded call below.  The lesson generalises past this
   commit: a guard placed at a shared tail is bypassed by whatever the
   callers do before they reach it, so "chokepoint" is a claim about the
   call graph and has to be checked against one.
5. *`engine.commit`'s `capture_page_state` call is left unguarded*, with
   the reachability argument written down at the call site: every
   `PreparedEdit` reaching it has passed `prepare_plan`'s gate, and the
   verifier below re-proves the frame anyway.
6. *`visual_baseline_direction` returns `DIRECTION_DEGENERATE` rather than
   propagating* an unprovable frame — fail-closed (a non-cardinal
   direction refuses the show) and it keeps the census scripts running on
   pathological corpus pages.
7. *The `/UserUnit` semantics cells moved down a layer.*  They asserted
   `page_visual_frame` mirrors MuPDF for `0` / `-2` / `-2.5`; the frame
   now refuses those, so the mirroring is pinned on `read_user_unit` (the
   reader still mirrors, deliberately) and the refusal is pinned on the
   frame.  No measurement changed.

### Commit 3 — point-verified glyph boxes from the embedded program

Scope: §3.1, §3.2 "Glyph boxes" / "Placement" / "Cursor replay", and the
first two bullets of §3.3.  `plan.py`'s gate is UNTOUCHED (commit 4).

**Red, stage 1 (nothing implemented) —
`.venv\Scripts\python.exe -m pytest test_scripts/test_glyph_boxes.py -x -q`:**

```
ERROR collecting test_scripts/test_glyph_boxes.py
test_scripts\test_glyph_boxes.py:23: in <module>
    from model.text_commit.cid_fonts import (
E   ImportError: cannot import name 'read_embedded_font_program' from
    'model.text_commit.cid_fonts'
1 error in 0.65s
```

**Red, stage 2 (API + cache landed, `glyph_unit_box` still a stub returning
`GlyphBox(None, "glyf_unavailable")`) — the informative red:**

```
box = GlyphBox(units=None, reason='glyf_unavailable')
oracle = (63.0, -140.0, 961.0, 757.0), gid = 0
>       assert box.reason is None, f"gid {gid} refused: {box.reason}"
E       AssertionError: gid 0 refused: glyf_unavailable

FAILED ...::test_padded_point_box_brackets_the_oracle_on_simple_glyphs
FAILED ...::test_padded_point_box_brackets_the_oracle_on_composite_glyphs
FAILED ...::test_lsb_differs_from_xmin_glyphs_are_covered_exactly
FAILED ...::test_left_side_bearing_comes_from_the_hmtx_tail_array
FAILED ...::test_a_zeroed_glyph_header_refuses_rather_than_bounding[simple]
FAILED ...::test_a_zeroed_glyph_header_refuses_rather_than_bounding[composite]
FAILED ...::test_synthesised_composite_matches_the_oracle_under_a_2x2_scale[False]
FAILED ...::test_synthesised_composite_matches_the_oracle_under_a_2x2_scale[True]
FAILED ...::test_a_self_referencing_composite_refuses
FAILED ...::test_gid_at_or_past_num_glyphs_is_out_of_range
FAILED ...::test_truncated_glyph_data_reports_a_parse_error
FAILED ...::test_cache_invalidates_when_the_font_program_is_rewritten
FAILED ...::test_registry_owns_a_glyph_box_cache_cleared_by_bump_generation
FAILED ...::test_a_second_units_per_em_face_brackets_the_oracle_too
14 failed, 10 passed in 4.07s
```

Two of the stage-2 passers were then STRENGTHENED because they could not
fail against the stub (CLAUDE.md §5.1): the cache-agrees-with-the-free-
function cell now also asserts the served box is a real box, and the OTTO
cell now asserts a real box BEFORE the rewrite.  The rest were red at stage
1 or carry real content the skeleton happened to satisfy (the closed-slug
tuple, the memo, the layer guard).

**Green:** 20 tests in `test_scripts/test_glyph_boxes.py`, none skipped (the
second-face cell finds its installed face); `test_layer_boundaries.py` 4/4
including the new `model/ -> scripts//fontTools` AST guard; 462 passed / 1
skipped / 2 xfailed across `-k "cid or font or type0 or glyph"`.

**Measured (shipped module, fixture face upem 256, 50,483 glyphs):**

| quantity | value |
| --- | --- |
| padded box contains `fz_bound_glyph`, 300 simple gids | 300/300, 0 refused |
| padded box contains `fz_bound_glyph`, 30 composite gids | 30/30, 0 refused |
| max deviation of the UNPADDED point box from the oracle | 0.0000 units (simple AND composite) |
| gids with `lsb != xMin`, whole font | 2 (both simple, both +1; 0 composites) |
| `glyph_unit_box` cost | 34.4 ms / 1,000 non-empty gids |
| `parse_truetype_glyph_program` first touch per font | 15.7 ms (3.5 MB program) |

The point box is not merely *contained* by the oracle — it EQUALS it on all
330 sampled gids, so the 1-unit pad is pure margin and the box is as tight
as the control box allows.

**Deviation 1 from the step's instructions (MEASURED, followed the
measurement).**  The instruction said the left side bearing for
`gid >= numberOfHMetrics` is "the last metric".  It is not: OpenType
(ISO/IEC 14496-22 §5.2.5) repeats the last long metric's ADVANCE only, and
the BEARING comes from the trailing `int16 leftSideBearing[]` array.  The
fixture face discriminates on exactly one gid (50482, the only one past
`numberOfHMetrics = 50482`): the tail-array bearing (-143) equals the
header `xMin`, shift 0, and the padded box contains the oracle with the
expected 1 unit of margin; the last-long-metric bearing (-115) gives shift
+28 and puts the box **27 units clear of real ink** — a false-safe in the
gate.  `hmtx`'s length also settles it arithmetically: 201,930 bytes =
50,482 x 4 + 1 x 2, i.e. exactly one trailing 2-byte entry.  Implemented as
the tail array; pinned by
`test_left_side_bearing_comes_from_the_hmtx_tail_array`, which asserts both
that the shipped rule brackets the oracle and that the rejected rule
differs by more than the pad.  PITFALLS entry filed.

**Deviation 2 (evidence gap closed conservatively).**  The plan's composite
rule says nothing about the `lsb - xMin` shift on composites, and the
spike's 3/3,001 one-unit deltas were all simple glyphs.  Scanning ALL 50,483
gids: 2 mismatches, both simple, both +-1; **zero composites have
`lsb != xMin` on any face measured here**, so whether FreeType translates a
composite outline the way it translates a simple one is UNPROVEN.  A
1-unit pad is safe under either reading when `|shift| <= 1`, so the shift is
applied uniformly and a composite with `|shift| > 1` is refused
(`composite_unsupported`) rather than guessed at.  Cost: 0 refusals on the
measured corpus.

**Decisions worth keeping.**

1. *The header cross-check runs BEFORE the shift, not after.*  The header
   box and the raw point box are the same quantity in the same frame, so
   honest glyphs agree exactly; comparing after the shift would refuse
   every glyph whose bearing legitimately differs from `xMin` — i.e.
   exactly the two gids the shift exists for.
2. *`SCALED_COMPONENT_OFFSET` is honoured, and it is MEASURED, not assumed.*
   A synthesised composite (a 1.5x scale on a component at offset
   (400, 200)) moved MuPDF's bound by exactly 200 units when the flag was
   set and by 0 when it was not.  The offset-readings-are-far-apart cell
   pins the discrimination so the paired scale cases cannot both pass under
   a single reading.  The synthesis overwrites a wide `loca` slot IN PLACE
   (trailing bytes are unread once `MORE_COMPONENTS` clears), so no `loca`
   offset has to be rewritten.
3. *The cache re-parses the fetched bytes instead of trusting
   `capability.glyphs`.*  The capability's table offsets were derived from
   the bytes present at BUILD time; a program rewritten since would be
   addressed with stale offsets.  Re-parsing alongside the fetch keeps the
   bytes and the offsets that address them always in agreement, and the
   one-slot memo makes it once per font per prepare (15.7 ms).
4. *`hmtx`/`hhea` were NOT promoted to required tables in the sfnt pass.*
   "Bit-for-bit existing behaviour" means every program that parses today
   still parses; a font without `hmtx` still yields a usable presence
   proof, and only the ink-bound caller refuses (`glyf_parse_error`).  Same
   discipline for `unitsPerEm`: carried as read, range-checked at the use
   site.  A `ttcf` member's `glyf`/`hmtx` offsets are rebased onto the
   container so one byte string addresses everything.
5. *`strict_overlap_depths` is duplicated, not imported from `plan.py`.*
   Commit 4 hands the planner a `GlyphBoxCache`, so `plan -> glyph_boxes` is
   the edge that must exist; importing the other way would cycle.  Six
   lines, with the reason at the definition.
6. *The AST guard covers all of `model/`, not the two named files.*  The
   rule is a layer rule, it lands green across the layer, and a
   file-scoped guard would miss the next module that reaches for
   `scripts/`.
7. *The second-upem cell reuses `TRICKY_FONT_PATH`* (the existing
   availability-gated convention) rather than inventing a new machine
   path.  It buys upem 1024 AND the SHORT `loca` format, which the fixture
   face (`indexToLocFormat = 1`) never exercises.

**Post-commit hardening (second commit, caught by an advisor pass on the
finished slice).**  The re-homed `predict_glyphs` checked `Tfs`, `Th`, `Tc`
and the `Tm x CTM` product for finiteness but NOT the per-glyph declared
width, which is document evidence like the rest.  `/DW` is finiteness-checked
at capability-build time; `/W` entries are not, and a PDF number token like
`1e400` lexes to `inf` through `float()`.  Confirmed red before the fix by
poisoning one `w_records` entry on the fixture capability:

```
>       assert predicted.slug == "text_state_unusable"
E       AssertionError: assert None == 'text_state_unusable'
E        +  where None = PredictedShow(glyphs=(
E            PredictedGlyph(index=0, cid=2014, gid=2014, cursor_x=0.0,
E                           origin_user=(72.0, 700.0)),
E            ... origin_user=(inf, nan)),
E            PredictedGlyph(index=3, cid=11722, gid=11722, cursor_x=inf,
E                           origin_user=(inf, nan))), slug=None).slug
1 failed, 4 passed
```

A successful prediction carrying `origin_user=(inf, nan)` is not a cosmetic
defect: NaN box edges make every comparison in `strict_overlap_depths`
False, so an unguarded NaN reads as "these two painters do not overlap" — a
FALSE-SAFE admission in commit 4's gate, the exact failure the gate exists
to prevent.  Fixed by refusing (`text_state_unusable`) the moment a width, a
TJ kern, or the running cursor goes non-finite.  PITFALLS entry filed.

The same pass closed the other half of the gap it exposed: `tj_items` and
`predict_glyphs` were shipped with NO direct coverage (section 3.3's first
two bullets name only `test_glyph_boxes.py` and the guard), so commit 4's
gate would have exercised ~120 lines of re-homed cursor arithmetic only
indirectly, through admit/refuse verdicts — where a sign error in the kern
term or a `Tw` applied to 2-byte codes surfaces as a mysterious verdict flip
rather than as a failing sum.  Five cells added: the TJ re-lex recovers the
kerns `ShowOp.decoded_bytes` drops; a byte range that does not reproduce the
recorded operand is refused (both an overrun and a single flipped hex
digit); a leading kern places glyph 0 at `-n/1000 * Tfs * Th` and each
subsequent glyph at `+(w0/1000 * Tfs + Tc) * Th` with no `Tw` term; the
three no-capability / no-relex / odd-byte-count refusals; and the
non-finite-width refusal above.  Only the last was red against the shipped
code — the other four PIN re-homed arithmetic that already worked, and are
labelled as pins in the file.

Two residuals recorded rather than chased: a `glyf` program with no `hmtx`
refuses EVERY gid (`glyf_parse_error`) rather than returning an unshifted
box — deliberate, since an unshifted box is not a safe substitute for an
unknown one, but commit 5's census should confirm no corpus font lands in
that population wholesale; and `test_glyph_boxes.py` is now 29 tests.

### Commit 4 — exact painter geometry in the duplicate-painter gate

Scope: §3.2 "Population" / "Gate (plan.py)" / "Caching / ordering", and the
second and third bullets of §3.3.  `glyph_boxes.py` is commit 3's; the only
addition to it here is the `units_per_em` accessor the placement needs.

**Red (nothing implemented) —
`.venv\Scripts\python.exe -m pytest test_scripts/test_p4b2_admission_gate.py
test_scripts/test_p4b2_production_pins.py
test_scripts/test_p4b2_falsification_matrix.py -q`:**

```
E   assert "identical source painter's glyph ink overlaps the target ink by"
      in 'identical source painter overlaps target core by 22.800pt x 7.200pt'
E   AttributeError: 'GlyphBoxCache' object has no attribute 'units_per_em'
E   assert isinstance(PreparedEdit(...), PlanRejection)      # the /W rows
E   assert ['collapsed-tm-stroke-tr1', 'collapsed-tm-stroke-tr2'] == []

FAILED ...test_p4b2_admission_gate.py::test_wide_declared_width_over_narrow_glyphs_is_admitted
FAILED ...::test_tj_twin_leading_kern_that_reaches_the_target_is_refused_by_ink
FAILED ...::test_tj_twin_leading_kern_that_stays_clear_is_admitted
FAILED ...::test_non_fill_render_mode_twin_falls_to_the_reach_path[1|2|7]
FAILED ...::test_overlapping_rasters_are_refused_by_the_glyph_ink_arm[tz50|tz150|
        ts+3|ts-3|rotate90|rotate270|tm45|shear-ctm]
FAILED ...::test_a_twin_raised_clear_of_the_target_is_admitted
FAILED ...::test_a_rise_that_cancels_a_baseline_offset_still_refuses
FAILED ...::test_the_overlap_detail_never_carries_document_text
FAILED ...::test_the_cache_serves_the_units_per_em_of_the_program_it_parsed
FAILED ...test_p4b2_production_pins.py::test_w_continuum_twin_is_rejected  [16 ids]
FAILED ...test_p4b2_production_pins.py::test_core_band_twin_is_rejected[dy-7.3|dy+7.3]
FAILED ...test_p4b2_falsification_matrix.py::test_production_arm_has_zero_false_safes
FAILED ...::test_production_arm_never_admits_more_than_the_exact_arm_proves
FAILED ...::test_production_arm_recovers_the_frozen_tip_false_admits
39 failed, 192 passed in 47.16s
```

Ten cells of `test_p4b2_admission_gate.py` passed at that point and are
labelled PINS in the file: the eight raster-safety cells (an overlapping
raster must not be admitted — already true through the advance/reach path),
the simple-font metric clone, and the unreliable-origin target, whose string
the advance quad's own early return already emits.  The
`..._refused_by_the_glyph_ink_arm` twin of each safety cell is what makes
those eight non-vacuous: it fails unless the EXACT arm owns the refusal.

**Green:** 32 cells in `test_p4b2_admission_gate.py`, 21 in
`test_p4b2_production_pins.py`, 181 in `test_p4b2_falsification_matrix.py`,
44 in `test_text_commit_duplicate_painter_gate.py`; `ruff check .` clean,
`mypy model/ utils/` unchanged-clean.

**Falsification matrix, four arms over 62 shapes, measured AT THIS COMMIT**
(a false safe is a row whose two single-painter rasters overlap AND whose arm
admits):

| arm | false safes |
| --- | --- |
| `exact` (spike verdict function, out of tree) | 0 |
| `baseline` (`glyph_boxes=None`, advance quad live) | 22 |
| `reach` (`glyph_boxes=None`, `_painter_advance` stubbed) | 2 |
| **`production` (this commit: real cache + real replacement CIDs)** | **0** |

`baseline ∖ production` recovers all 22 rows, among them both R5 core-band
rows, the F4 negative-`Tc` walk-back, the whole 16-row `/W` continuum,
`neg-tc-same-origin` and the two `collapsed-tm-stroke-tr*` rows.  No row is
admitted in production that the spike's arm calls an overlap.

These are NOT the frozen tip's numbers, and the difference is deviation 2's
doing: `reach` was 4 at the frozen tip and is 2 here, because the
`_painter_reach` determinant precondition is arm-independent — it fixes
`collapsed-tm-stroke-tr1/tr2` in the `reach` arm too.  `baseline` is
unchanged at 22 (its advance quad still admits that pair; only `production`
and `reach` refuse it).  The `>= 19` assertions in the matrix are floors, so
they still hold, but read the table above as "at this commit", not as the
tip's.

**(a)–(h) outcomes.**

| cell | outcome |
| --- | --- |
| (a) 16 `/W` rows + `second_dy = ±7.3` | REJECT with the glyph-ink string; the two characterizations deleted, both strict-xfails now plain passes |
| (b) `second_clone_width=1500` at `offset −32` | ADMITTED (raster overlap 0); the same page with no glyph cache refuses, `…overlaps target core by 4.000pt` |
| (c) `TJ` leading kern `+6000` / `+4000` at `offset 74` | REFUSED by ink / ADMITTED (raster 0); the no-cache arm refuses BOTH |
| (d) `Tr 1`, `Tr 2`, `Tr 7` twins | the reach-path string verbatim, never the glyph string |
| (e) `_simple_metric_clone_plan` | unchanged, `…overlaps target core by…` |
| (f) target with `origin_reliable=False` | `…cannot prove target placement`, unchanged |
| (g) `Tz 50/150`, `Ts ±3`, `/Rotate 90/270` + offset CropBox + `/UserUnit 2`, 45° `Tm`, 2×2 shear CTM | rasters overlap (874–6,316 px); all eight refused, and all eight by the EXACT arm |
| (h) 62-shape matrix, production arm | 0 false safes (table above) |
| (i) refusal detail | ASCII, measurements only; no source/replacement character, no resource name |

**Deviation 0 (arithmetic in the step, not a design change).**  §3.3 says
"the 8 `/W` cases"; `W_CASES` in `test_p4b2_production_pins.py` is 16
parameters (2 declared widths x same/distinct CIDToGID x 4 offsets), and the
matrix carries the matching 16 rows.  All 16 are converted and all 16 pass —
no cell of the intended set was dropped.

**Deviation 1 (instruction vs. fixture; followed the fixture).**  The step
named `painter_matrix_fixtures.replace_show_with_tj` for the `TJ` cells.
That mutator asserts `stream.count("<hex> Tj") == 1`, which a two-painter
page never satisfies — both painters show the same bytes.
`_build_second_show_doc` already builds the shape directly
(`second_operator="TJ"`, `second_leading_kern=…`), so the cells use that and
the fixture module is untouched.

**Deviation 2 (MEASURED; a pre-existing false safe the new arm surfaced).**
The step requires "0 production false-safes" on the matrix.  Two rows failed
it — `collapsed-tm-stroke-tr1/tr2`, a rank-1 `Tm` (`1 0 0 0`) with
`1 Tr 8 w`, 1,948 overlapping ink pixels — and MEASURED at the pre-slice tip
they were already false safes in BOTH other arms (`baseline_admits=True`,
`reach_admits=True`), so this commit inherited them rather than caused them.
The exact arm correctly declares a stroked twin ambiguous and hands the
decision to `_painter_reach`, whose bound silently stops being a bound when
the text-space → visual map is singular: the reach *quad* maps to a
*segment*, its extent on the lost axis is exactly `0.0`, and `0.0 > 0.05` is
False.  Closed red-first
(`test_a_stroked_twin_under_a_singular_text_matrix_is_refused`) by requiring
the determinant of the two mapped unit vectors to be finite and non-zero.  A
FILLED collapsed outline paints nothing at all (measured: empty ink mask) and
is still admitted — through the exact arm, not through reach — and that half
is asserted too, so the fix cannot degenerate into "refuse every singular
twin".  PITFALLS entry filed.

**Deviation 3 (three existing CID gate tests changed; simple-font behaviour
byte-identical).**  The step's "existing gate tests unchanged" holds for the
simple-font path, which never enters the arm.  Three CID cells in
`test_text_commit_duplicate_painter_gate.py` state pre-slice
*approximations*, not properties, and had to move:

1. `…raised_by_its_own_rise_still_fails_closed` — the twin's own `Ts` now
   places its ink exactly, and a two-em rise clears a 0.91-em glyph box.
   The raster oracle confirms the two painters share NO pixel, so admitting
   it leaves nothing on top of the edit.  Rewritten as a boundary pair
   (`0.5·Tfs` and `0.8·Tfs` still refuse), with the admitted case carried in
   the new file behind an `overlap == 0` assertion.  Same reason for
   dropping the `raised twin` row from
   `test_commit_pipeline_never_leaves_a_twin_visible` (replaced by a half-em
   rise, which still is a ghost).
2. `…distinct_cid_font_fails_closed` — still refuses, now with the ink
   string: a bound read from the twin's OWN program does not care whether
   its glyphs are the target's, so `font identity` is no longer the reason.
3. `…tj_twin_whose_leading_kern_pulls_ink_over_the_target…` — still refuses,
   now by measured overlap instead of `exact extent`, because the kern is
   re-lexed rather than bounded away.

Every flipped expectation is anchored to `painters_overlap_pixels`, never to
the new code's own verdict.

**Decisions worth keeping.**

1. *The arm's precondition is `glyph_boxes` AND `replacement_cids`, not
   `glyph_boxes` alone.*  The ink this edit will PAINT counts as much as the
   ink it replaces, and a caller that supplied only the cache would silently
   bound the target by its source glyphs.  It also gives the matrix a real
   seam: `registry.glyph_boxes = None` reproduces the frozen tip exactly, so
   `baseline` and `reach` stay comparable with the spike's numbers instead of
   being quietly redefined by this commit.
2. *An ambiguous exact verdict forces the REACH branch, never the advance
   quad.*  Falling back to the declared advance would hand the decision to
   the bound this arm exists to distrust — the `Tr 1/2/7` cells fail loudly
   if that ever regresses.  The `unproven = "exact extent"` semantics are
   preserved by simply suppressing `exact_extent`.
3. *`units_per_em` comes from the cache, not from the capability.*  The boxes
   are re-parsed from the bytes present at fetch time (commit 3's decision
   3); a capability's `glyphs.units_per_em` was read at BUILD time.  Mixing
   them scales freshly-measured ink by a stale em, so the accessor serves the
   em of the same pass and `clear()` drops it alongside the boxes.
4. *`'` and `"` twins are ambiguous by rule.*  Their recorded range folds a
   `T*` line break or a `Tw`/`Tc` assignment whose effect on the origin this
   arm does not prove; only `Tj` and `TJ` are replayed.
5. *A blank `loca` span is skipped; a refused box returns.*  The two are
   different answers — "proven to paint nothing" widens no union, "cannot
   tell" must not be treated as empty — and conflating them would be a
   false-safe with no symptom.
6. *Negative `Tz` is supported, negative `Tfs` is not.*  `scale_units_to_text`
   normalizes x explicitly for mirrored text but not y, so a negative font
   size would yield an inverted rect; the arm requires `Tfs > 0` and only
   `Th != 0`.
7. *The aggregate AABB prefilter can only admit.*  Every pair it skips lies
   inside an aggregate pair already proven disjoint, so it carries no verdict
   of its own — which is why `pos-tc-gap-aggregate` (aggregate boxes overlap,
   per-glyph ink does not) still reaches the pairwise loop.

**Residual for commit 5.**  The census wrapper forwards the new kwargs
through `**extra` but supplies none of them, so its baseline arm is still
the pre-slice gate; wiring the production arm is commit 5's own scope.

Two numbers commit 5's census should put a value on, neither measured here:

1. Deviation 2's determinant precondition is arm- and font-independent.  It
   makes EVERY twin under a singular text-space map unadmittable through
   `_painter_reach`, including simple-font and non-Type0 twins that never
   reach the exact arm.  It is strictly fail-closed, so it costs value, not
   safety — but the corpus cost is unknown.
2. The exact arm is gated on `glyph_boxes AND replacement_cids`, so the
   admission rate it buys on real documents is still only the matrix's, not
   the corpus's.

### Commits 5 and 6 — census production arm, glyf-box re-validation, and admission benchmark

**Red (pre-implementation tree, `.venv\Scripts\python.exe -m pytest
test_scripts/test_p4b2_shadow_census.py -x -q`):**

```
ERROR collecting test_scripts/test_p4b2_shadow_census.py
ImportError: cannot import name 'PRODUCTION_AMBIGUOUS_SLUGS' from
'scripts.measure_p4b2_shadow_census'
1 error in 0.55s
```

**Provenance note.**  This step's implementation, tests and docs were
already present, uncommitted, in the working tree at the start of the
committing session (an interrupted prior attempt at this same step; `git
reflog`/`git stash list` confirmed no other branch or stash held the work,
and `HEAD` sat exactly at the commit this step's precondition names). The
above red log was therefore not captured live by the committing session.
Before trusting or committing anything, that session re-verified
provenance directly: `git stash push -- scripts/measure_p4b2_shadow_census.py`
(isolating the implementation while keeping the new test file in place),
re-ran `.venv\Scripts\python.exe -m pytest
test_scripts/test_p4b2_shadow_census.py -x -q`, and reproduced the
IDENTICAL `ImportError: cannot import name 'PRODUCTION_AMBIGUOUS_SLUGS'`
failure above verbatim, then `git stash pop` to restore. The green run (15
passed) was also re-executed live, not taken on the logbook's word. The
diffs (implementation, tests, benchmark script, docs) were read in full
before either run.

**Design, as built (measured against §3.4, one deviation).**  The
`production` arm is the REAL `plan.duplicate_source_painter_detail`
called with the real kwargs `prepare_plan` passes at its call site
(`model/text_commit/plan.py:1173-1187`): `streams=dict(snapshot.streams)`
(`capture_page_streams`, cached per page), `replacement_cids =
target_capability.cid.encode_strict(target_text)` (the census's own
stand-in for the replacement — the SAME text re-encoded, mirroring the
funnel's own self-check pattern at `scripts/measure_type0_funnel.py:928`,
not a different string; the "after" half of the target ink therefore never
widens past the "before" half — a stated limitation of this arm's VALUE
measurement, never of its safety, since the O1 cross-check below only ever
compares SOURCE ink, the only half actually painted on the page),
`glyph_boxes=registry.glyph_boxes`, `frame=page_visual_frame(page)` (cached
per page; `None` on `UnsupportedPageGeometryError` skips the row entirely,
matching `prepare_plan`'s own refusal before the gate is ever reached).

The row's admit/refuse VERDICT is decided by calling the REAL private
`plan._painter_glyph_ink`/`plan._glyph_ink_overlap` directly — frame
space, the actual production arithmetic — not by re-deriving it.  A
SEPARATE, module-level function, `_derotated_glyph_ink`, is a
same-preconditions, same-order MIRROR of `plan._painter_glyph_ink`
(matching its five-condition check in the same order: `origin_reliable`,
`render_mode`, then the three finiteness checks, then `units_per_em`) that
places every glyph through `painter_geometry.place_text_rect(...,
evidence.base_matrix)` instead of the visual frame, keyed by glyph INDEX so
it lines up with `PainterEvent.glyphs[index].bounds` (the O1 device box)
for the same show.  This mirror is used for exactly two things — the
per-glyph O1 containment check (`glyf_box_contains_o1`/
`glyf_box_violation`) and a diagnostic slug for why a row fell to reach —
and is NEVER the source of the overlap decision itself: an axis-aligned
box is not rotation-invariant, so a box built in derotated space could
disagree with the frame-space box about whether two shapes overlap even
when both correctly bound the same ink (advisor catch, see PITFALLS "A box
re-derived in a different coordinate space cannot stand in for the
original in an overlap test").  `ShadowCensus._shadow_ink` runs both
computations for every glyph-ink call and counts any None-ness or
glyph-count disagreement between them under `production_mirror_disagrees`
(closed key, MUST be 0 — it is what certifies the mirror has not drifted
from the real gate, which is the precondition for
`glyf_box_violation == 0` meaning anything about production).

**Deviation from §3.4 (measured, not guessed).**  §3.4 names four
ambiguous slugs: `non_fill_render_mode`, `origin_unreliable`,
`tj_relex_failed`, `no_cid_capability`.  Measured against
`glyph_boxes.PREDICTION_SLUGS` (`model/text_commit/glyph_boxes.py:237-243`,
already read before this step per the harness note): `predict_glyphs`
returns FIVE distinct slugs, not two of the four named —
`odd_byte_count` and `gid_unresolved` are real, distinct failure reasons
with no natural home in the other four, and folding them into
`tj_relex_failed` would misreport why a row fell to reach.
`PRODUCTION_AMBIGUOUS_SLUGS` is therefore `glyph_boxes.GLYPH_BOX_REASONS ∪
glyph_boxes.PREDICTION_SLUGS ∪ {non_fill_render_mode, origin_unreliable}`
(13 slugs), derived from the module constants rather than typed out, so a
renamed slug cannot drift silently out of the closed key set (the pattern
`_DEVICE_LOAD_BEARING_REASONS`/`ROW_REASON_KEYS` already use in this file).

**Counters and identities, as built.**  `production_rows_decided`,
`production_exact_safe`, `production_overlap`,
`production_ambiguous.<slug>` (13 keys), `glyf_box_contains_o1`,
`glyf_box_violation`, `production_mirror_disagrees`,
`production_vs_exact.<prod>_<exact>` (16 keys, `{safe, overlap, ambiguous,
unavailable}` on both axes — `exact_overlap_same_baseline` and
`exact_overlap_cross_baseline` both collapse to `overlap`, `error`
collapses to `unavailable`), `production_delta_exact_safe`,
`production_reach_overlap`, `composed_all_gates_pass_production` (mirrors
`composed_all_gates_pass`: `reach_all_gates_pass +
production_delta_exact_safe - production_reach_overlap`).  Two new
identities: `production_partition` (`production_exact_safe +
production_overlap + Σ production_ambiguous.<slug> == twin_rows`) and
`composed_identity_production` (a self-consistency re-derivation of
`composed_all_gates_pass_production`, mirroring `composed_identity`'s own
existing pattern).  `evidence` is now fetched ONCE per row (outside and
before both the exact arm's `try:` and the production arm's call) and
shared — calling `_page_evidence` a second time is SAFE (page-keyed cache,
its own `_evidence_pages_seen` counting guard) but would have left a real
`UnboundLocalError` hazard if the exact arm's own fetch failed inside its
`try:` and a sibling block tried to read the same local name outside it
(see PITFALLS "A cached per-page bundle fetched from two call sites...").

**Green.**  All 15 tests in `test_scripts/test_p4b2_shadow_census.py` pass
(9 pre-existing + 6 new: closed-key coverage, the synthetic-corpus safety
and partition assertions, and the corrupted-glyf-header document).  Two
pre-existing tests updated for the two new identity keys
(`test_synthetic_corpus_partitions_rows_and_holds_the_identities`,
`test_privacy_no_identity_reaches_the_report`) — not a behaviour change,
the closed-key set literally grew.

**Measured on the synthetic two-document corpus** (`overlapping`: a `/W 0`
clone twin sharing the target's real glyf outlines; `abutting`: the same
font, twin painted exactly one advance-width away):

```
twin_rows = 4
production_rows_decided = 4        (0 fell to reach)
production_exact_safe = 2
production_overlap = 2
production_mirror_disagrees = 0
glyf_box_contains_o1 = 16
glyf_box_violation = 0
production_delta_exact_safe = 2
production_reach_overlap = 1
composed_all_gates_pass_production = 2   (= 1 + 2 - 1)
reach_all_gates_pass = 1
production_ambiguous.* = 0 everywhere
identities: all True (production_partition, composed_identity_production
  included)
```

**Corrupted-glyf-header document (red-first, its own test).**  A third,
one-off document built the same way as `abutting` but with the SOURCE
text's first gid's glyf header zeroed to `(0,0,1,1)` (test-side sfnt
arithmetic, copied rather than imported per the harness note — MuPDF
ignores this header entirely, so a header-trusting reader would silently
under-bound live ink): `production_ambiguous.glyf_header_disagrees > 0`
and `glyf_box_violation == 0`, confirmed.

**Sealed run: pending, orchestrator.**  Not run here (sealed corpus is
outside this step's scope and this session never opens `test_files/`).
Exact command line (script's real CLI, `scripts/measure_p4b2_shadow_census.
py:658-700`):

```
python scripts/measure_p4b2_shadow_census.py <sealed corpus paths...> --json
```

(add `--expect KEY=VALUE` to override a sealed constant, or
`--no-candidate-fonts` to skip loading system candidate faces — neither is
needed for a plain sealed run).  Report `composed_all_gates_pass_production`
against the spike's 6,618 (§3.4) and the exact arm's own
`composed_all_gates_pass` once the run completes.

**Benchmark (`scripts/benchmark_p4b2_admission.py`, new, measurement-only,
n as stated, aggregates only — no wall-clock number below is committed
anywhere but this logbook, per the harness note on machine-specific
timings):**

```
two-painter fixture (n=30):    cold  p50 50.4 / p95 53.9 / p99 54.2 ms
                                warm  p50 20.0 / p95 21.2 / p99 49.1 ms
                                warm_glyph_boxes_cached = 3

dense same-bytes bucket,       cold  p50 83.8 / p95 102.7 ms
275 twins (n=10):               warm  p50 62.0 / p95 114.5 ms
                                warm_glyph_boxes_cached = 3
                                (first recording -- no prior P4-B2-admission
                                 baseline on this shape to compare against;
                                 this run IS the new baseline)

glyph-box parse (2,000 gids,
repeat=5):                     25.8 ms / 1,000 gids

preview keystroke path, warm
(P3-C's own dense corpus,
n=30), vs. the RECORDED
baseline in benchmarks/
p3c-acceptance-2026-08-23.json
(gitignored; plans/task13-p3c-
preview-postprepare-latency.md
does not exist in this repo):  baseline p50 267.3 / p95 315.6 ms
                                current  p50  98.5 / p95 113.3 ms
                                ratio    p50 0.37x / p95 0.36x  (not a
                                 regression, but a ~2.7x swing across two
                                 separately-run benchmark sessions on
                                 different machine states is too large to
                                 read as a measured speedup either --
                                 there is no comparable same-session
                                 baseline for this slice, not evidence of
                                 an improvement; this slice never touches
                                 the preview path, so no directional claim
                                 is made either way, and this
                                 slice never touches the preview path)
acceptance_failures: []
```

`warm_glyph_boxes_cached == 3` on both corpora confirms the cache's
`(font_xref, digest, gid)` key: the target/twin pair paints 2 distinct
gids and the replacement paints 1 more, and a 275-way repeat of the SAME
decoded bytes adds no further entries.

**Docs.**  PITFALLS: two new entries (the derotated-mirror-cannot-decide
finding, the double-fetch double-count near-miss).  ARCHITECTURE §10.1.7:
a new paragraph documenting the production arm and the benchmark.  TODOS:
the P4-B2 production-slice item extended with commits 5+6's summary and
the sealed-run command line; "next" now points at the closing-docs commit.
