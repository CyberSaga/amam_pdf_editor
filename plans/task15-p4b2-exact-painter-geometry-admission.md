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
