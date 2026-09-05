<!-- Produced 2026-09-05 by a judge-panel design workflow (designs: minimal-wrapper, first-class-pair, safety-first; winner minimal-wrapper 25/23 vs 15/16; the safety-first design reached the judges truncated). Not yet started. -->

# T16-4 — Tandem "bold" commit for Office-exported CJK PDFs

## Goal

**The task's premise is refuted by measurement, and the plan is retargeted accordingly.**

T16-4 as written assumes a *painter pair*: a fill show (`Tr 0`) plus a separate identical-bytes stroke twin (`Tr 1`) over the same glyphs, refused today because `duplicate_source_painter_detail` (`plan.py:581`) sees the twin as an indistinguishable same-bytes painter. **No such pair exists in the fixture.** `test_files/[HVAC_DWG_ID] …-Bb版.pdf` contains **zero `1 Tr` operators**. Its synthetic bold is a **single show op in render mode 2** (fill-then-stroke): `… /F5 14.04 Tf … Tm  2 Tr  0.40114 w  0 G  [<hex>] TJ`. `get_texttrace()` reports two device spans (type=0 then type=1, adjacent seqno) for that *one* operator — the MuPDF artifact already recorded at `docs/PITFALLS.md:2812`, which `PITFALLS.md:3001-3002` and `TODOS.md` T16-4 then read as two painters.

Retargeted goal: **admit `render_mode == 2` at Tier 0** for a single-string show, with a proven stroke ink bound, keeping the duplicate-painter gate's protection intact. There is no tandem machinery to build — a splice confined to the string operand cannot touch `2 Tr` or `0.40114 w`, both of which sit *before* `op_start`, so the stroke leg is preserved by construction.

Two hard dependencies must land in the same slice or the change is a no-op:

1. **Single-item `TJ` admission.** `plan.py:1000-1005` refuses every non-`Tj` operator with `NOT_SINGLE_LITERAL_TJ` **before** the render-mode gate at `plan.py:1006`. All nine mode-2 shows in the fixture are `TJ` arrays. Measured end-to-end: every one refuses `not_single_literal_tj` today; the gate T16-4 names is unreachable.
2. **A stroke ink bound in `_painter_glyph_ink`** (`plan.py:463-521`, refusal at `:488`) for the page-2 shape, which has real same-bytes twins. Without it those three shows refuse permanently even after (1).

**Honest acceptance:** page 1 `seq 7/11/15` (single-item, no twins) become committable in Phase A; page 2 `seq 49/50/51` (single-item, one mode-0 twin each) in Phase B. Page 1 `seq 9/13` (two-item arrays, kerns between the items) stay refused — Tier 1's problem. Until this lands, non-strict `tiered` falls back to `legacy`, which drops the stroke leg (`PITFALLS.md:3002`); that remains true for every refused show.

---

## Evidence

All measured on this machine, `.venv/Scripts/python.exe`, PyMuPDF 1.27.1. Fixture referenced by path only; no document text or font names reproduced.

### E1 — There is no painter pair (raw stream + replay)

| page | `Tr` operands | `w` operands | `gs` invocations | replay render modes |
|---|---|---|---|---|
| 0 | `{'2': 6}` | `{'0.40114': 5, '0.456': 1}` | 2 | `{0: 175, 2: 6}` (181 shows) |
| 1 | `{'2': 3}` | `{'0.51429': 3, '1.5': 1}` | 2 | `{0: 112, 2: 3}` (115 shows) |
| 2 | `{}` | `{'1.5': 1}` | 2 | all 0 |

`w == font_size / 35` exactly on every mode-2 show (14.04/35 = 0.40114; 15.96/35 = 0.456; 18/35 = 0.51429) — the Word synthetic-bold convention. **Zero `1 Tr` anywhere in the file.**

### E2 — `get_texttrace()`'s `linewidth` is not the document pen

Page 0 type-1 spans report `linewidth` 0.702 / 0.798 = exactly `0.05 × size`, against real pens 0.40114 / 0.456 (**1.75×**). Page 1's type-1 spans (size 18) report `1.5` against a real pen of 0.51429 (**2.9×**) — 1.5 is a *stale graphics-state* `w` from elsewhere on the page, not a size-proportional fallback. Two different wrong values from two different mechanisms. **Never read the pen from texttrace; read it from the `w` operator via replay.**

### E3 — Operator shape and today's real refusal (`prepare_plan`, real registry)

Binding is unambiguous once `expected_origin` is in the space the binder uses (`inspect.py:819-842`: `origin_user × frame.visual`, i.e. **visual page space, not user space**). With the correct origin:

```
p0 seq= 7 items=1 -> not_single_literal_tj
p0 seq= 9 items=2 -> not_single_literal_tj
p0 seq=11 items=1 -> not_single_literal_tj
p0 seq=13 items=2 -> not_single_literal_tj
p0 seq=15 items=1 -> not_single_literal_tj
p1 seq=49 items=1 -> not_single_literal_tj
p1 seq=50 items=1 -> not_single_literal_tj
p1 seq=51 items=1 -> not_single_literal_tj
```

(`p0 seq=2` is `/F2`, a simple font, single-item `TJ`, 65 same-bytes twins.) Binding is **not** a blocker; the `TJ` gate is. With a *wrong* origin space the same targets report `ambiguous_source_match` / `evidence_mismatch` — a probe artifact, not a code path to fix.

### E4 — The duplicate gate, called directly (bypassing the `TJ` gate)

```
p0 seq= 2  SIMPLE font           dup-gate -> None            (admitted; 65 twins provably disjoint)
p0 seq= 7  painter_ink=None      dup-gate -> None            (no twins, early-out at plan.py:626-629)
p0 seq=11  painter_ink=None      dup-gate -> None
p0 seq=15  painter_ink=None      dup-gate -> None
p1 seq=49  painter_ink=None      dup-gate -> "identical source painter cannot prove target placement"
p1 seq=50  painter_ink=None      dup-gate -> "identical source painter cannot prove target placement"
p1 seq=51  painter_ink=None      dup-gate -> "identical source painter cannot prove target placement"
```

`_painter_glyph_ink` returns `None` for every mode-2 show (`plan.py:488`), so the exact arm short-circuits at `plan.py:698-702`. **This is the measurement that makes Phase B necessary**: leaving `plan.py:488` untouched permanently refuses page 2.

### E5 — Pen space: CTM scales it, `Tm` and `Tz` do not

Synthetic 200×200 page, `/helv`, `(H) Tj`, `2 w`, zoom 64, each variant measured against its own `0 Tr` twin at the same device position:

| variant | outset (l, t, r, b) |
|---|---|
| A: `Tm` identity, CTM identity, 20 pt | `(1.0, 1.0, 1.0, 1.0)` |
| B: `q 2 0 0 2 0 0 cm`, 10 pt | `(2.0, 2.0, 2.0, 2.0)` |
| C: `Tm = 2 0 0 2`, 10 pt | `(1.0, 1.0, 1.0, 1.0)` |
| D: `200 Tz`, 20 pt | `(1.0, 1.0, 1.0, 1.0)` |

The text-stroke pen is **user space**. Any bound folding `Tm` (or `Tz`, which lives in the text matrix) into the pen **under-states it whenever `Tm` scale < 1** — the false-safe direction at the duplicate gate.

### E6 — Miter overshoot is real, large, and glyph-dependent

`/helv 40 Tf`, `6 w` (half-pen 3.0), `10 M`, zoom 48, stroked vs filled:

| glyph | join | max outset | ×half-pen |
|---|---|---|---|
| `H` | miter | 3.000 | 1.00 |
| `4` | miter | 3.562 | 1.19 |
| `V` | miter | 4.896 | 1.63 |
| `A` | miter | 5.083 | 1.69 |
| `W` | miter | 6.771 | 2.26 |
| `M` | miter | **13.625** | **4.54** |
| `A` | round | 3.021 | 1.01 |
| `V` | round | 3.021 | 1.01 |

A half-pen-only bound is **measurably wrong** at a fail-closed site. The `max(miterlimit, 0.5)` factor (`PITFALLS.md:2917`, `scripts/painter_geometry.py:207-291`) is mandatory wherever under-bounding admits. Round/bevel joins collapse to half-pen, as the pinned formula says.

### E7 — Page geometry and the halo

`page_visual_frame` on both pages: `user_unit=1.0`, `rotation=0`, `visual = (1, 0, 0, -1, 0, 841.92)`, so `σmax(frame.visual) == 1.0`. Half-pen in visual points: 0.2006 / 0.2280 / 0.2571. Miter-factored bound: `0.40114/2 × 10 = 2.0057` — **larger than `_HALO_MARGIN_PT = 2.0` (`verify.py:47`)**. Adopting the miter bound at `target_bbox_page` would roughly *double* V0d's exempt region. This number is why the two bounds must not be unified (see Decision D4).

### E8 — ExtGState

Page 0 applies `/GS7 gs` and `/GS8 gs` (stream offsets 150, 164) **before every mode-2 show**. The objects are `<</Type/ExtGState/BM/Normal/ca 1>>` and `<</Type/ExtGState/BM/Normal/CA 1>>` — neither declares `/LW`, `/LJ`, or `/ML`. A blanket "any `gs` in scope ⇒ pen unprovable" rule would silently kill the feature on the only document that motivates it.

---

## Decision

Winner: **the minimal-splice design** (no pairing, no binding change, no patch change), with four grafts. Rationale below is anchored to the evidence, not to the designs.

**D1 — No pairing signal, no `SourceSpanBinding` change.** One logical bold run is one `ShowOp`; the 1:1 contract (`inspect.py:82-96`, `bind_source_text` `inspect.py:930-1177`, `AMBIGUOUS_MATCH` at `:1090-1094`) is already correct for this shape (E3). The admission key is `ShowOp.render_mode` (`replay.py:115`), a stream fact. `get_texttrace` type-0/type-1 adjacency is a *device* signal that cannot be read back from the stream and must never be an admission key (E2).

**D2 — No `patch.py` change.** One `StreamReplacement`, as today. `2 Tr` and the `w` operand sit before `op_start` (page 0 `seq=7`: `string 1651..1679`, `op 1651..1682`), so a string-operand splice preserves render mode, pen width, joins, and stroke colour by construction. `PreparedEdit.replacement` stays singular; `engine._patchset`, `apply_patchset` (`patch.py:132-176`), `build_reversal_patchset`, and `preview.py`'s PatchSet construction are untouched. Undo/redo inherits `AppliedPatch.prior_storage` exact-restore (`patch.py:86-129`); preview == commit is automatic because both consume the same cached `PreparedEdit`.

*Recorded reason not to build tandem machinery* (so the next reader does not re-derive the refuted premise): an N-op group would require `SourceSpanBinding.show → shows: tuple`, `PreparedEdit.replacement → tuple`, `_content_token` (`plan.py:786`) folding every replacement, `engine._patchset` emitting N replacements, `verify._target_operator_failure` (`verify.py:415-476`) looping instead of proving exactly one token, plus a brand-new leg-to-leg consistency obligation (both legs must receive byte-identical replacements or the ghost reappears in a new form). Its only instance in this corpus is N = 1.

**D3 — Splice the *inner* string item of a single-item `TJ`, not the array token.** `_target_operator_failure`'s Tier 0 branch (`verify.py:430-445`) demands the replacement lex as **exactly one** STRING/HEXSTRING token spanning the whole buffer. Splicing `[<hex>]` wholesale breaks that and would force a Tier 1-style isolated replay; splicing the inner `<hex>` keeps `[`, `]`, and ` TJ` byte-identical and keeps the invariant literally true. `_SPLICEABLE_SHOW_OPERATORS` (`patch.py:57`) already contains `"TJ"`, so the mechanism-level chokepoint is satisfied. `tj_items` (`glyph_boxes.py:191`) already re-lexes the items with `token.start`/`token.end` in hand and discards them — a sibling helper returning absolute offsets is the whole change.

**D4 — Two different bounds at two sites. Do not unify them.** The direction of error is opposite:

| site | error if under-bounded | error if over-bounded | bound to use |
|---|---|---|---|
| `target_bbox_page` (`plan.py:1218-1240`) → V0d halo | **false reject** (V0d fires, commit reverts, zero mutation) | proof erosion: more page exempt from the diff | `(w/2) · σmax(ctm_linear ∘ frame.visual)` — **honest, no miter factor** |
| `target_core` (`plan.py:630-637`) and `_painter_glyph_ink` → duplicate gate | **false safe** (an overlapping twin is admitted and silently damaged) | more refusals | `(w/2) · max(M, 0.5) · σmax(…)` — **conservative, miter-factored** |

The miter factor is mandatory at the conservative site (E6: `M` overshoots half-pen by 4.54×) and must be kept *out* of the honest site (E7: `2.0057 > _HALO_MARGIN_PT = 2.0`, so adopting it would roughly double V0d's exempt region on the fixture's own pen). This is the same reasoning `_glyph_ink_overlap`'s docstring (`plan.py:537-560`) already uses to keep two tolerances apart.

**D5 — σmax, not MuPDF's `max|elem|`, and the helper lives in `model/`.** `scripts/painter_geometry.stroke_expansion` is not importable from a production layer (CLAUDE.md §3.1) and encodes MuPDF's `max(|a|,|b|,|c|,|d|)`, which `PITFALLS.md:2917` records as **under**-bounding the true stretch (√2 under rotation, up to 2 under shear). A new pure helper next to `combined_linear` (`transforms.py:323`) uses the exact largest singular value:

```
E=(a+d)/2, F=(a-d)/2, G=(b+c)/2, H=(b-c)/2
sigma_max = hypot(E, H) + hypot(F, G)
```

A round pen of radius `w/2` maps to an ellipse whose largest semi-axis is exactly `σmax · w/2` — tight, not merely an upper bound. The linear part is `combined_linear(_IDENTITY_TM, show.ctm)` composed with `frame.visual` — **never** `combined_linear(show.tm, show.ctm)` (E5). Comment the divergence from the pinned `scripts/` formula as deliberate, and reconcile with `test_p4b2_oracles.py::test_bboxlog_stroke_text_rect_is_o1_union_plus_stroke_expansion` **by test, not by import**, so nobody unifies them back toward the under-bound. This is a scoped, evidence-backed narrowing of `PITFALLS.md:2918`'s "treat every non-fill render mode as ambiguous by rule": that conclusion was about the *oracle's* defect, and it stays in force everywhere the oracle is the source of truth.

**D6 — Phase B closes the degenerate-outline hole before it opens the stroke arm.** `plan.py:517` skips a glyph whose `loca` span is blank with the comment "proven to paint nothing". True for a fill; **false for a stroke** — the pen strokes the collapsed path (`PITFALLS.md:2900-2904`, which already fixes the verdict as `ambiguous / degenerate_stroke`). Admitting mode 2 through that `continue` silently drops stroked ink from the union at both the target and the twin site. So Phase B's *first* change is `continue → return None` under a non-fill mode; the stroke arm is only then permitted.

**D7 — Modes 1, 3, 4-7 stay refused, structurally.** Mode 1 (stroke-only) has no fixture and no fill leg. Mode 3 is invisible. Modes 4-7 **add the glyph outlines to the clipping path** — a persistent state effect on everything painted afterwards, exactly the hazard class the `'`/`"` refusal at `patch.py:49-56` guards. The ladder must name them explicitly, not refuse them incidentally.

**D8 — `gs` is resolved by the planner, not by replay.** `replay_page_streams` (`replay.py:372`) takes only `(xref, bytes)` pairs and has no document handle; it is called with bare stream lists from `inspect.py`'s form-XObject check and `verify.py`'s isolated replay. Replay therefore only **captures** ExtGState names in scope (the pattern `marked_content.admit_show_wrappers` already uses for `/OC`); the planner resolves them against the page `/Resources /ExtGState`. Ladder: key **present ⇒ apply**; key **absent ⇒ leave unchanged** (E8's case — the fixture takes this branch); resource dict or object **unreadable, or value non-finite ⇒ refuse**.

---

## Affected modules

| File:line | Change | Phase |
|---|---|---|
| `model/text_commit/replay.py:229-238` (`_State`) | add `line_width=1.0`, `line_join=0`, `miter_limit=10.0`, `extgstate_names: tuple[str, ...] = ()` | A |
| `model/text_commit/replay.py:240-251` / `:253-265` (`snapshot`/`restore`) | all four fields in **both** — the field added to `snapshot` and forgotten in `restore` leaks a stale pen across `q … Q` | A |
| `model/text_commit/replay.py:629-633` (`Tr` dispatch arm) | add `w`, `j`, `M`, `gs` arms beside it | A |
| `model/text_commit/replay.py:90-121` (`ShowOp`) | add the four fields, **defaulted** so hand-built `ShowOp`s across the suite stay valid | A |
| `model/text_commit/replay.py:434-472` (`_record_show`) | populate them next to `render_mode=state.render_mode` (`:470`) | A |
| `model/text_commit/transforms.py:323` (beside `combined_linear`) | new pure `sigma_max(linear) -> float` | A |
| `model/text_commit/plan.py` (near `_painter_core_quad`, `:329`) | new `_stroke_outset_visual(show, *, frame, miter: bool) -> float | None` | A |
| `model/text_commit/glyph_boxes.py:191` (`tj_items`) | new sibling returning absolute `(start, end)` per string item | A |
| `model/text_commit/plan.py:1000-1005` | admit `TJ` with `array_item_count == 1`; multi-item refused under its own code | A |
| `model/text_commit/plan.py:1006-1010` | split `rise` from render mode; ladder admits `{0, 2}`; mode-2 pen/`gs` proof | A |
| `model/text_commit/plan.py:1274-1300` (`_build_tier0`) | splice the inner item range for `TJ` | A |
| `model/text_commit/plan.py:1218-1240` | outset fallback `target_bbox` by the **honest** bound (caller-supplied bbox untouched — it already reflects rendered ink) | A |
| `model/text_commit/plan.py:630-637` (`target_core`) | outset by the **conservative** bound | A |
| `model/text_commit/plan.py:1412` (`_build_tier1`) | explicit `render_mode != 0` refusal at the top | A |
| `model/text_commit/dto.py:16` (`RejectReason`) | `TJ_MULTI_ITEM_ARRAY`, `STROKE_BOUND_UNPROVEN`, `STROKE_BOUND_TOO_LARGE`, `DEGENERATE_STROKE_GLYPH` | A / B |
| `model/text_commit/plan.py:517` (degenerate `continue`) | `return None` when `render_mode != 0` — **before** any stroke arm | B |
| `model/text_commit/plan.py:463-521`, `:488` (`_painter_glyph_ink`) | admit mode 2; pad each visual glyph box by the conservative bound | B |
| `model/text_commit/verify.py` (Tier 0 property list) | new post-condition: `Tr`/`w` operand bytes unchanged at their original offsets | A |
| `docs/PITFALLS.md:2812`, `:3001-3002`, `:2918` | **amend**, do not duplicate | docs |
| `TODOS.md` T16-4 | correct the premise; record the ceiling | docs |

`_content_token` (`plan.py:786`) gains **no** new parameter: the pen is derivable from the fingerprint-determined stream, the same argument `plan.py:141-144` already makes for `background_bbox_page`. The bound reaches the token through `target_bbox`, so two plans differing only in `w` already produce different tokens.

Every change is inside `model/`; no layer boundary is crossed and `lint-imports` is unaffected. Replay gains **no** `fitz` parameter (D8) — check that explicitly against `model-no-qt` and the resource-guard budget assertions in `evidence.py`.

---

## Fail-closed gates

| Condition | Reason code | Detail |
|---|---|---|
| `show.rise != 0.0` | `UNSUPPORTED_TEXT_STATE` | unchanged; must survive the split of `plan.py:1006` |
| `render_mode` ∈ {1, 3} | `UNSUPPORTED_TEXT_STATE` | `render_mode={n}`; no fill leg / invisible |
| `render_mode` ∈ {4, 5, 6, 7} | `UNSUPPORTED_TEXT_STATE` | `render_mode={n} adds glyphs to the clipping path` — its own branch, named, never incidental |
| `operator == "TJ"` and `array_item_count != 1` | `TJ_MULTI_ITEM_ARRAY` | kerns between items; Tier 1's problem. **Not** `NOT_SINGLE_LITERAL_TJ` — a distinct gate gets a distinct code |
| inner-item byte range does not re-lex to the recorded operand | `NOT_SINGLE_LITERAL_TJ` | integrity failure; never paper over |
| mode 2 and `line_width` non-finite, or `== 0.0` | `STROKE_BOUND_UNPROVEN` | `0 w` is device-thinnest, which half-pen under-states |
| mode 2 and any `extgstate_names` entry unresolvable, or its `/LW`, `/LJ`, `/ML` non-finite | `STROKE_BOUND_UNPROVEN` | resource dict or object unreadable ⇒ refuse. Key absent ⇒ **admit unchanged** (E8) |
| mode 2 and replay ran without page context (`extgstate_names` unprovable) | `STROKE_BOUND_UNPROVEN` | the `inspect.py` / `verify.py` bare-stream call sites degrade here rather than crash |
| `σmax` non-finite or `<= 0.0` | `STROKE_BOUND_UNPROVEN` | |
| `abs(w) · max(M, 0.5) > 0.5 · font_size` | `STROKE_BOUND_TOO_LARGE` | fixture ratio: `0.40114 × 10 / (0.5 × 14.04) = 0.571` — 43% headroom, uniform across all nine shows. Refuse rather than admit a halo so fat V0d proves nothing |
| **(B)** degenerate `loca` span under `render_mode != 0` | `DEGENERATE_STROKE_GLYPH` | `plan.py:517`; `PITFALLS.md:2900-2904` |
| mode 2 reaching `_build_tier1` | `UNSUPPORTED_TEXT_STATE` | `max_tier` defaults to 0, so the fence is free and deletes an unproven verification surface (`_grown_verify_bbox`, `background_bbox_page`, `plan.py:1424-1440`) |
| twin overlap after the conservative outset | existing `"identical source painter overlaps target core by …"` | no new string, no new code |

Every refusal must leave the document byte-identical (`doc.tobytes()` comparison, the pattern `test_text_commit_boundaries.py` already uses).

---

## Steps

Red-first throughout. **Show the failing output before each implementation step.** Run tests with `.venv\Scripts\python.exe -m pytest` only.

**Step 0 (evidence, no code).** Re-run E1/E2/E3/E5/E6/E7/E8 on the implementer's machine and paste the numbers into the plan. Amend `TODOS.md` T16-4 (the premise), `PITFALLS.md:3001-3002` (the "patch both painters together" instruction that produced it) and `:2812` (which already has the mechanism), and add **one** new pitfall — *"`get_texttrace()`'s `linewidth` is never the document pen"* with both failure modes from E2 (`0.05 × size` fallback on page 0; a stale graphics-state width on page 1). Regenerate the index. Do this **before** any gate is written: the wrong premise is the thing most likely to be re-derived.

**Step 1 (RED) — replay evidence.** `test_text_commit_replay.py`: `ShowOp.line_width` picks up `w`; `1 w q 5 w Q … Tj` restores 1.0 not 5.0; `j`/`M` likewise; `/GS1 gs q /GS2 gs Q … Tj` reports `('GS1',)`. Fails with `AttributeError`.

**Step 2 (GREEN).** `replay.py` per the table. Defaults on `ShowOp` so no existing hand-built op breaks.

**Step 3 (RED) — the σmax helper.** `test_stroke_outset_scales_with_the_ctm_and_not_with_the_text_matrix`, pinned to E5: `cm 2 0 0 2` doubles it, `Tm 2 0 0 2` does not, `Tz 200` does not. Plus `test_stroke_outset_carries_user_unit_and_rotate` (`/UserUnit 2` doubles; `/Rotate 90` unchanged) — dropping `/UserUnit` is the false-accept direction at the gate site (`_grown_verify_bbox` docstring, `plan.py:1345-1350`). Plus `test_sigma_max_exceeds_mupdf_max_elem_under_rotation_and_shear`, pinning the deliberate divergence from `scripts/painter_geometry.stroke_expansion` (√2 rotation, ~2 shear, `PITFALLS.md:2917`).

**Step 4 (GREEN).** `transforms.sigma_max` + `plan._stroke_outset_visual`.

**Step 5 (RED) — single-item `TJ`.** `test_single_item_tj_array_is_admitted_at_tier0`: synthetic `[(text)] TJ`, fill mode, advance-neutral replacement ⇒ a `PreparedEdit` whose `replacement` covers **only** the inner string token, with `[`, `]`, ` TJ` byte-identical pre/post. Plus `test_target_operator_reproven_for_a_tj_inner_item_splice` (`verify.py:430-445` still applies verbatim) and `test_multi_item_tj_array_is_refused_with_its_own_code`. Fails with `not_single_literal_tj`.

**Step 6 (GREEN).** Sibling to `tj_items`; relax `plan.py:1000-1005`; `_build_tier0` splices the inner range. **Do not touch `patch.py`.**

**Step 7 (RED) — the render-mode ladder.** `test_text_commit_stroke_admission.py`, every case failing first: mode 2 with a proven pen admitted (currently `unsupported_text_state` — the headline gate); modes 1/3/4-7 refused, parametrized, asserting code **and** that the detail names the mode, with 4-7 carrying their own clip-path assertion; `0 w` refused `STROKE_BOUND_UNPROVEN`; `/GS1 <</LW 3>> gs` refused; **`gs` without `/LW` admitted** (the fixture's own shape — guards against the blanket refusal that would silently kill the feature); dangling `/ExtGState` xref refused; `w · M > 0.5 · size` refused `STROKE_BOUND_TOO_LARGE`; non-zero `rise` still refused.

**Step 8 (GREEN).** `dto.py` codes (comment naming this slice and why each is new, per the Task 11 note at `dto.py:55-58`); the ladder and pen proof at `plan.py:1006`; the honest outset at `plan.py:1218-1240`.

**Step 9 (RED → GREEN) — the duplicate gate.** `test_a_stroked_target_core_is_outset_before_the_twin_overlap_test`: a same-bytes twin whose core sits ~0.1 pt outside the *un-outset* target core. It must **first pass as ADMITTED** — that is the red state, a demonstrated false safe — then fail closed once `plan.py:630-637` outsets with the conservative bound. Assert the existing refusal string form, unchanged. Add `test_miter_factor_is_load_bearing_at_the_duplicate_gate` pinned to E6's `M`-glyph number (4.54× half-pen), so nobody drops the factor because a probe on `H` looked small.

**Step 10 (RED → GREEN) — Tier 1 fence.** Force `ADVANCE_MISMATCH` on a mode-2 target with `max_tier=1`. Red: a Tier 1 candidate is built. Green after the explicit refusal at `plan.py:1412`.

**Step 11 (RED → GREEN) — end to end, Phase A.** Synthetic single-item-`TJ` mode-2 page: prepare → commit → assert COMMITTED at Tier 0; the post-commit stream still holds `2 Tr` and the byte-identical `w` operand at their original offsets (the direct regression pin for *"bold silently vanishes"*); the rendered stroke outset is unchanged post-commit at zoom 64 (proves it at the pixel level, not only at the byte level); preview token == commit token; `AppliedPatch.revert` restores the stream byte-identically. Then `test_every_stroke_refusal_leaves_the_document_byte_identical` across every refusal case above.

**Step 12 — Phase A regression + fixture pins.** Full text-commit suite. Pin: page 0 `seq 7/11/15` and page 1 `seq 49/50/51` **change refusal code** from `not_single_literal_tj` to their new codes (`seq 7/11/15` → ACCEPTED; `seq 49/50/51` → `duplicate_source_painter` / *"cannot prove target placement"*, the E4 measurement); page 0 `seq 9/13` → `TJ_MULTI_ITEM_ARRAY`. `ruff check .` and `.venv\Scripts\python.exe -m mypy model/ utils/`.

**Step 13 (RED) — Phase B, the degenerate hole first.** `test_a_degenerate_glyph_under_a_stroke_is_refused_not_skipped`: a synthetic font with a blank `loca` span, shown at mode 2. Red today: `plan.py:517` skips it and the union is silently short. Green after `continue → return None` under a non-fill mode, with `DEGENERATE_STROKE_GLYPH`. **This test must be green before Step 15 is written.**

**Step 14 (RED) — Phase B, the payoff.** `test_a_stroked_target_with_a_same_bytes_twin_can_prove_its_placement`, built to the page-1 shape (a mode-2 run at one size whose bytes repeat as a mode-0 run at another size, far away). Red: refuses *"cannot prove target placement"* (E4).

**Step 15 (GREEN).** `_painter_glyph_ink` admits mode 2 and pads each visual glyph box by the conservative bound. Leave every other refusal in that function untouched. Re-run `test_p4b2_admission_gate.py` **unchanged** — its false-safe pins, including `test_a_stroked_twin_under_a_singular_text_matrix_is_refused` (`PITFALLS.md:2952-2954`), must stay green without edits; if one needs editing, stop and reopen the design.

**Step 16 — verification and docs.** Full suite, `ruff`, `mypy`. `docs/ARCHITECTURE.md`: the new replay evidence fields, the new reason codes, and the deliberate σmax-vs-`max|elem|` divergence. `TODOS.md`: T16-4 scope closed with the honest ceiling (advance equality still refuses any bold edit that changes the consumed advance, and `max_tier=0` ships, so non-strict `tiered` still falls back to legacy). `git mv` the plan to `plans/archive/` in the completion commit.

---

## Open questions

1. **`/OC` layer boundaries and `line_width` scope.** `w` appears *inside* `BT … ET` in this fixture (legal). Replay dispatches uniformly so nothing special is needed, but confirm no marked-content wrapper resets the graphics state in a way `admit_show_wrappers` currently proves inert for fills only.
2. **`p0 seq=2`** is a simple-font (`/F2`) single-item `TJ` at mode 2 with 65 same-bytes twins, and the duplicate gate currently returns `None` (admits) for it (E4). After Phase A it reaches the render-mode gate. Is its `tier0_reject_reason` clear, and does the conservative `target_core` outset change that admission? Measure before Step 12's pin is written.
3. **The 0.05 pt tolerance at `plan.py:773`** was calibrated for advance quads. With outset cores it may now be inside the noise of the outset itself. Check whether it should scale with the bound.
4. **Multi-item `TJ` for the user's actual gesture.** If the controller passes the whole title line as `target_text`, the model may bind across shows and refuse for an unrelated reason. Check what `controller/` actually passes before claiming the title is editable.
5. **`/ExtGState /Font`** can change the font at a show the engine believes is using the `Tf` resource — a pre-existing, unrelated gap now on the radar because `gs` is being read for the first time. Register it separately; out of scope here.

---

## Pivot conditions

- **Step 5 red does not reproduce** (a single-item `TJ` already admits): the `TJ` gate is not the blocker the E3 measurement says it is. Stop and re-measure before writing any gate.
- **Step 9's red state does not admit** (the false safe is not demonstrable): the conservative outset at `target_core` is not load-bearing on the branch assumed. Re-derive which branch reaches `_strict_overlap_depths` (`plan.py:772`) before changing `target_core`, and do not ship a widened bound whose need is unproven.
- **The honest bound at `target_bbox_page` produces a spurious `VERIFICATION_FAILED`** on a real mode-2 target: E6 says an acute-vertex glyph can exceed half-pen. That is fail-closed (revert, zero mutation), so **do not** react by fattening `target_bbox` toward the miter bound — that erodes V0d past its 2.0 pt halo (E7). Instead refuse the target and register the shape.
- **Step 13 cannot be made red** (no synthetic font produces a degenerate `loca` span through this path): **Phase B does not ship.** Phase A alone is a complete, useful slice; `_painter_glyph_ink` keeps refusing mode 2 and page 1's three shows stay refused, which is the correct fail-closed outcome.
- **Any `test_p4b2_admission_gate.py` pin requires editing** in Step 15: the stroke arm has weakened a proven gate. Revert Phase B and reopen the design.
- **A genuine `Tr 0` + `Tr 1` tandem pair is found in a real document:** the N-op ripple in D2 becomes real work, and the gate exemption for the paired twin must be keyed on `(stream_xref, string_start, string_end)` membership in **this** PatchSet — never on "same bytes + same origin + same font", which would silently admit an unrelated third same-bytes painter, exactly the protection the gate exists to give. The gate must still run in full against every show *not* in the PatchSet, and advance equality must hold independently for both legs (they may carry different `Tc`/`Tw`/`Tz`).