# T16-4X — Glyph-coverage expansion: every show shape Tier 0 can prove

## Current state (2026-10-23)

- S0 and S1 landed (see the log in section 7). S2 (render-inert marked content) is next.
- S10 landed 2026-10-23, uncommitted at the time of writing: a page whose /Annots
  array holds an INLINE annotation dictionary is refused with
  `annotations_not_indirect` (prepare, commit, plan preview) instead of raising
  `AttributeError` out of `prepare`. Tests: `test_scripts/test_text_commit_direct_annots.py`.
- Registered, not done: `annotation_tool.py` get_all/toggle still raise on that
  shape; the model does not gate the rebuild/consent fallthrough for it, only
  the View hides the button (TODOS.md, T16-4).

## 0. Reading of the request

"Expand T16-4: cover all kinds of glyphs to eliminate every jump."

The product goal is to edit selected text while preserving unrelated glyph
positions, painting order and appearance through preview, commit, undo/redo,
and save/reopen. Tier 0 admission is one intermediate gate, not completion.
The verifier constrains raster changes outside the target halo; that alone
does not prove correctness inside the halo or in every viewer.

**Interrogation amendment (2026-09-06, Astra):** this is a proposed expansion
for selected fixtures, not a plan that already covers all of `test_files`.
The recursive inventory contains 2,933 PDFs: 11 at the root, 32 in
`sample-files-main`, 3 in `Test-PDF-Files-master`, and 2,887 in
`veraPDF-corpus-staging`. The nine fixture roles below cannot establish that
other PDF features are absent. Every "zero-corpus" statement below means
zero in that measured sample only. Historical measurements remain dated;
they are not the current admission verdict.

Completion of the full-corpus goal requires accounting for every file and
page (including unreadable, encrypted and text-free cases), and testing real
changed selections through preview, verified commit, undo/redo and
save/reopen. Report successful edits separately from safe refusals and
unmeasured cases, with both document and edit weighting. Refusing an unsafe
edit preserves the document but does not count as successful edit coverage.
Reversing characters is a useful equal-advance probe; it skips palindromes
and says nothing about missing glyphs or ordinary width-changing edits.

The existing Tier 1 compensation path must be measured alongside Tier 0.
The §8 gaps (including Form XObjects and paragraph targets) remain unmet
parts of the user's goal, even if every proposed slice below passes. Do not
weaken verification or silently use legacy fallback to claim coverage.

Two standing rules from the repo govern every slice: **red-light first**
(the failing test is shown before the gate is written) and **fail closed
with a stable code** (no admission without a document-derived proof; every
refusal leaves the document byte-identical).

---

## 1. Census (measured 2026-09-06, `.venv`, PyMuPDF 1.27.1)

Fixtures referenced by role only; no document text, font names or file
paths reproduced. Scripts: `scripts/measure_tier_funnel.py` (edit-level,
identity replacement) and a show-shape probe to be promoted as
`scripts/census_show_shapes.py` in S0.

### 1.1 Edit-level funnel (4 fixtures: prose-1p, office-report-23p, xobject-1p, colored-bg-8p)

| stage | count | breakdown |
|---|---|---|
| samples (lines + word runs) | 1265 | resolve survives 100 % |
| bind survivors | 292 | losses: `undecodable_target` 623 (**funnel artefact** — the script binds without a registry, so every CJK target counts here; production runs the CID leg), `target_in_form_xobject` 150, `target_reconstruction_unverified` 129, `no_source_match` 56, `evidence_mismatch` 15 |
| plan survivors | **0** | **292/292 refuse `not_single_literal_tj`** (office-report-23p 245, prose-1p 41, colored-bg-8p 6, xobject-1p 0). Produced by the funnel's *mirror* of the plan gates, whose order is not production's (§1.4) — plausible, not a production verdict; S0 replaces the mirror |

Every edit that reaches the planner dies at the operator gate. Nothing
behind it (marked content, render mode, fonts) has ever been measured on a
real edit because this gate fires first (`plan.py:1000-1005`).

### 1.2 Show-shape census (direct page streams; shows, not edits)

| fixture | shows | `Tj` | `TJ` 1 item, no kern | `TJ` multi-item kerned | `Tr 2` | wrapped in marked content | fonts |
|---|---|---|---|---|---|---|---|
| office-report-23p | 2237 | 0 | 1959 (87.6 %) | 278 (12.4 %) | 141 (6.3 %) | **2237/2237** (struct 2190, artifact 47) | TrueType WinAnsi emb 1614, Type0 Identity-H 543, TrueType WinAnsi unembedded 80 |
| colored-bg-8p | 103 | 0 | 99 | 4 | 0 | **103/103** (struct) | TrueType 58, Type0 45 |
| horizontal-1p | 32 | 25 (22 hex) | 0 | 7 | 0 | **32/32** (struct) | Type0 29, TrueType 3 |
| vertical-1p | 28 | 0 | 21 | 7 | 0 | **28/28** (struct); TRM rotated 28/28 | Type0 25, TrueType 3 |
| complex-layout-2p | 2507 | 2507 (hex) | 0 | 0 | 0 | 2498/2507 (struct 1769, **malformed pairing 595**, struct+ActualText 128, malformed+ActualText 6; 9 unwrapped) | **Type3 1621 (64.7 %)**, Type0 886; `origin_unreliable` 152 |
| prose-1p | 26 | 0 | 26 | 0 | 0 | 0 | Type1 WinAnsi unembedded (system face) |
| xobject-1p | 0 direct | — | — | — | — | — | all text inside Form XObjects (80/90 targets) |
| CAD-drawing-50p (T16-4 fixture) | 28043 | **27250 (97.2 %, hex)** | 317 (7 at `Tr 2`) | 476 (1.7 %; kerns are **word gaps**: 1788 vs 143 micro) | 9 | **28043/28043** (`/OC` layers, Task 13); TRM rotated 25655 (91 %); `Tz != 100` 4330 | Type0 Identity-H 27820, TrueType WinAnsi 223 |
| large-402p (60 pages sampled) | 5406 | 1883 (1517 hex; **334 at `Tr 3`, invisible**) | 0 | **3523 (65 %)**: micro 18571, mid 4181, word-gap 2169 | 0 | 23 | TrueType WinAnsi **unembedded 4407** (system face; symbolic flags on 152), Type0 924, TrueType emb 75; `Tc != 0` 4096, `Tw != 0` 64, TRM rotated 1064 |

**Amended 2026-09-08 (S1 fixture pins, measured):** the `28043/28043 (/OC layers)` figure above is unchanged — it is the whole-fixture census, and stands. But the nine `Tr 2` mode-2 bold shows this program is named after are NOT reachable through their `/OC` wrapping alone: all ten single-item bold targets (the nine plus the one simple-font `p0 seq=2` show) sit inside a **struct-content** marked-content wrapper, distinct from the fixture's `/OC` layers, and it is that wrapper's gate (`mc_wrapper_not_pure_layer`) that answers first once S1 removes the operator gate in front of it (`test_scripts/test_text_commit_s1_fixture_pins.py`). So "wrapped in marked content: `/OC` layers" describes the fixture in aggregate; it does not describe the bold shows this plan targets, which are struct-content wrapped like the Office corpus. See the tandem plan's Step 12 amendment for the full measurement.

Kern structure of the 278 kerned arrays (office-report-23p): kern numbers
**micro (<0.05 em) 944, mid 10, word-gap (≥0.2 em) 20**; item boundaries in
the TrueType arrays fall **inside a word 288 times**, at punctuation 169, next
to a real space byte 80; 170 kerned arrays are Type0. So the dominant kerned
shape is *pair kerning inside words*, not word gaps materialised as kerns —
this decides S4's design (§3 X5).

Text state across all nine fixtures: `Tc != 0` 4234 shows and `Tz != 100`
4330 (both admitted today), `rise != 0` **0**, `'`/`"` **0**, render modes
1/4-7 **0**, `/Differences` **0**. **Render mode 3 (invisible text) is
present: 334 shows on the 402-page fixture** (an OCR-style hidden layer) —
so it leaves the zero-corpus list and becomes slice S7 (§4). Symbolic
descriptor flags appear on 152 unembedded TrueType shows there (encoding
still the named WinAnsi, so the simple-font gate admits them today).

Type3 shape (complex-layout-2p, 174 fonts): `FontMatrix [.001 0 0 -.001 0 0]`
(one at `.00048828127`), `/Encoding` dict **with** `/Differences`, `/ToUnicode`
present, `/CharProcs`, `/Widths` array — the fully provable Type3 shape.

### 1.3 What the numbers say

1. **The operator gate is the whole story today**; behind it the
   marked-content gate refuses **100 % of Office-exported shows**
   (`struct_content` class, `marked_content.py:249`), so lifting the TJ gate
   alone moves the refusal from `not_single_literal_tj` to
   `mc_wrapper_not_pure_layer` and changes nothing for the user. S1 and S2
   must land together or be measured together.
2. Single-item `TJ` (T16-4 Phase A) covers 87.6 % of office-report-23p and
   96 % of colored-bg-8p by show count (75 % of vertical-1p; horizontal-1p
   is hex `Tj`, already admitted); the kerned remainder is intra-word
   micro-kerning (S4). **The single-item `TJ` gate has two emission sites**:
   `plan.py:1000-1005` and the CID leg's `string_kind != "hex"` refusal at
   `plan.py:1064-1074` — every `TJ` records `string_kind == "array"`, so
   relaxing only the first leaves every Type0 `[<hex>] TJ` (543/2237 Office
   shows and all nine CAD bold shows) refused under the *same code*. S1
   must relax both (§4 S1).
3. Synthetic bold (`2 Tr`) is 6 % of one Office fixture and the whole of
   the T16-4 motivation on the CAD fixture — real, but third in yield.
4. Type3 is 65 % of one fixture and 0 of every other: a whole-document
   class (LaTeX/bitmap/Excel exports), worth a slice, not a fixture-specific
   patch.
5. The CAD fixture is 97 % hex `Tj` on Identity-H — already the admitted
   operator/font shape — wrapped 100 % in `/OC` layers and 91 % rotated; its
   admission therefore rides on the Task 13 gates, its 9 bold shows on S1/S3,
   and its 476 kerned arrays (word-gap kerns, the token-wise case of X5) on
   S4. The 402-page fixture is the opposite corpus: 65 % kerned arrays with
   intra-word micro kerns (the collapse case of X5) and 81 % unembedded
   TrueType through a system face.
6. Invisible text (`3 Tr`, 334 shows) is a real jump class: the legacy
   engine re-inserts *visible* glyphs over a scan where the source painted
   nothing. Tier 0 admission is cheap and sound (no ink, so no ink bound and
   no twin can be damaged) — slice S7.
7. Everything else the taxonomy names (modes 1/4-7, `'`/`"`, rise,
   `/Differences`, Identity-V, CFF descendants, non-Identity CMaps) measures
   **0** on this corpus. Per the D7 discipline of the original plan they stay
   **refused by name**, with a registered slice that opens only when a corpus
   shows them (§8).

### 1.4 CAD-drawing fixture and the stale audit instrument

`audit_tier_coverage.py` (finished 12:02, 31 min for the 50 pages): **28,043
shows, 0 Tier 0 eligible, 28,043 `unsupported_text_state`**. The same script
reports office-report-23p as 2237/2237 `unsupported_text_state` and
vertical-1p as 28/28. That is not the production verdict: the audit's mirror
predicate (`audit_tier_coverage.py:62-72`) still folds `mc_depth != 0` into
`unsupported_text_state`, i.e. it predates the Task 13 P1 `/OC` admission and
the Task 13 P2 quarter-turn admission (`trm_uniform_scaled` is likewise
folded in). Both instruments therefore need an S0 fix before any slice can
be measured with them: the audit's predicates must call the production
gates (`admit_show_wrappers`, `admission_verdict`) instead of mirroring
them, and the funnel needs the CID leg (§1.1). Until then the only trustworthy
per-show numbers are the registry-free shape probe's and the direct
`admit_show_wrappers` call (271/271 struct refusals, §1.3). Why every
CAD census is slow: one page of the fixture decodes to a **71.5 MB** content
stream that `replay_page_streams(max_decoded_bytes=None)` takes ~194 s to
replay (3228 shows) — production refuses that page under the safe-replay
budget (`CONTENT_STREAM_TOO_LARGE`), so a census must either honour the
budget or report that page separately; never let it dominate a timing
figure. The same Step 0 measurement found the registry scope bug recorded as
S0-b in §4 — the instrument work paid for itself before any gate moved. The CAD shape
counts are in the §1.2 table (registry-backed probe, finished 12:15); the
T16-4 plan's E1–E8 already fix the bold shape on that fixture (page 0: 181
shows, 175 mode 0, 6 mode 2, all `[<hex>] TJ`; zero `1 Tr` in the file).

---

## 2. Coverage matrix

| axis | class | today | slice | corpus yield |
|---|---|---|---|---|
| operator | `Tj` literal/hex | admitted | — | — |
| operator | `TJ`, exactly one string item (a kern *before* the item is its own gate, S1) | `NOT_SINGLE_LITERAL_TJ` (two sites) | **S1** | 76–96 % of Office shows; 317 CAD |
| operator | `TJ`, several items, kerns between | `NOT_SINGLE_LITERAL_TJ` | **S4** | 12 % of Office shows |
| operator | `'` / `"` | `UNSUPPORTED_SHOW_OPERATOR` | S8 (register) | 0 |
| target | word inside a longer string item | `NO_MATCH`→`TARGET_RECONSTRUCTION_UNVERIFIED` | **S5** | every per-word edit on a line-per-item PDF |
| render mode | 0 | admitted | — | — |
| render mode | 2 (fill+stroke, Word bold) | `UNSUPPORTED_TEXT_STATE` | **S1** (pen proof), **S3** (twin bound) | 6 % Office; CAD title |
| render mode | 3 (invisible; OCR layers) | `UNSUPPORTED_TEXT_STATE` | **S7** | 334 shows on large-402p (6 %) |
| render mode | 1, 4–7 | `UNSUPPORTED_TEXT_STATE` | S8 (register; 4–7 never) | 0 |
| marked content | `/OC` default-visible layer | admitted (Task 13) | — | CAD fixture |
| marked content | `struct_content` (`/P <</MCID>>`), `artifact`, bare `BMC` | `MC_WRAPPER_NOT_PURE_LAYER` | **S2** | **100 % of Office shows** |
| marked content | `ActualText`, `Alt`, malformed pairing, unresolved | refused | stays refused (§8) | malformed 601 + ActualText-bearing 134 on one fixture |
| font | Type1/TrueType, Standard/WinAnsi/MacRoman, printable ASCII | admitted | — | — |
| font | same fonts, 8-bit non-ASCII codes (é, —, “ ”) | `ENCODING_FAILED` | S7a (register) | 0 on corpus, common in European prose |
| font | simple font with `/Differences`; symbolic built-in | `FONT_CUSTOM_DIFFERENCES` / `FONT_UNSUPPORTED_ENCODING` | S7b (register) | 0 |
| font | Type0 Identity-H / CIDFontType2 embedded | admitted (Task 12) | — | — |
| font | **Type3** with `/Differences` + `/ToUnicode` + `/Widths` | `FONT_TYPE3` | **S6** | 65 % of one fixture |
| font | Type0 CIDFontType0 (CFF), Identity-V, non-Identity CMaps, unembedded Type0 | `TYPE0_*` | S9 (register) | 0 |
| text state | `Tc`, `Tw`, `Tz > 0`, quarter-turn TRM | admitted | — | — |
| text state | `rise != 0` | `UNSUPPORTED_TEXT_STATE` | S8 (register) | 0 |
| edit kind | advance-changing replacement | `ADVANCE_MISMATCH` → legacy (`max_tier=0`) | **ceiling** §8.1 | most real edits |
| edit kind | multi-line / partial-line paragraph | `MULTI_SPAN_TARGET` | ceiling §8.2 | — |
| target | text inside a Form XObject | `TARGET_IN_FORM_XOBJECT` | ceiling §8.3 | 100 % of one fixture |

---

## 3. Design decisions (X1–X8; D1–D8 of the original plan stay in force)

**X1 — Preserve unrelated content; measure the actual edit path.** These
slices expand Tier 0 admission. They do not complete product coverage or
prove the legacy fallback safe. Tier 1 already supports compensated
advance changes; assess it before inventing another splice grammar or
layout path. Default and strict-mode changes still require their own
measured rollout decision (§8.1).

**X2 — Peel the onion in gate order, and re-measure after every slice.**
The classifier's gate order (`plan.py:855-1274`) means each slice exposes the
next dominant refusal. S0 promotes the shape census to `scripts/` so every
slice's acceptance includes the *same* two numbers: funnel plan-survival
rate and the new dominant refusal code. A slice that does not move the
survival rate on the fixture that motivated it has not landed.

**X3 — One splice primitive, three grammars, one proof dispatch.** Every
slice is "replace a byte range inside the recorded show operand with bytes
that (a) preserve the consumed advance and (b) re-lex to a declared grammar".
`PreparedEdit` gains `splice_kind` ∈ {`"string_token"` (today, and S1's inner
item), `"string_fragment"` (S5), `"tj_run"` (S4)} plus the fragment offsets
/ kern sum the proof needs, all folded into `_content_token` (`plan.py:786`)
so preview and commit stay identical by construction (WS-A). V0c's
`_target_operator_failure` (`verify.py:415-476`) becomes a dispatch on
`splice_kind`, and **each arm first asserts the range shape it expects
against the recorded show** (`string_token`: the range is the whole string
operand or the single inner item's range; `tj_run`: `[item_i.start,
item_j.end)`; `string_fragment`: strictly inside one item) before lexing —
the label alone must never select a weaker proof, because `PreparedEdit` is
cached and reused at commit (`pdf_text_edit.py:1740-1760`). Every arm gets
its own tamper test (a two-token payload under `string_token`, a mislabelled
kind, a range outside the item), extending
`test_text_commit_v0c_operator_proof.py`. V0a/V0b/V0d/V0e are untouched
because they never assumed a grammar. `_SPLICEABLE_SHOW_OPERATORS` (`patch.py:57`) already holds
`{"Tj","TJ"}` — no `patch.py` change until S8.

**X4 — Render-inert marked content is admissible; extraction-bearing marked
content is not.** A BDC whose property list carries only structural keys
(`MCID`, `Lang`, and for `/Artifact` its `Type`/`Subtype`/`BBox`/`Attached`)
has no effect on painting, and a splice strictly inside its span (proof
obligation 4, `marked_content.py:341`) cannot alter its pairing. **Probe
P-A (2026-09-06, 13 variants × 2 placements, fresh and after reopen):**
pixmap, `get_text("text")`, rawdict spans and words are identical wrapped vs
unwrapped for every inert class, for a named `/Properties` target (direct
and indirect) and for a struct wrapper nested in an Artifact; the same
splice inside and outside the wrapper renders identically. `ActualText` is
refused because it **replaces** extraction for its whole span (an outer
wrapper made the downstream show vanish from `get_text`), so V0c could not
see a wrong splice under it. `Alt` is measured extraction-neutral; it stays
refused on the accessibility ground alone (the tag would lie to a screen
reader) — the plan must not claim V0c as the reason. Two conditions: the
neutrality holds under the default text flags only (with a real
`/StructTreeRoot` and `TEXT_COLLECT_STRUCTURE` the rawdict block shape
changes), so V0c and `PageInterpretation` stay on the default flags and a
test pins that; and a `/Properties` resource inherited from a `/Pages` node
resolves to `props_unresolved` (`marked_content.py:110-114`) and must keep
refusing. Malformed pairing stays refused. The five proof obligations of
Task 13 P1 (`test_text_commit_mc_admission.py` docstring) are replicated for
the new classes. `update_marked_content_dependencies` already folds the
`/Properties` mapping and each named target's structured surface
(`_fold_target_structured`), so S2 adds **no** fingerprint code — it adds a
`/Lang`-mutation and a target-repoint staleness test proving the existing
fold covers the new classes. Unmeasured and therefore open (§10): a
StructElem-level `/ActualText` or `/Alt` reached through `/StructParents →
/ParentTree` (the tagged-PDF norm) — S2 Step 0 probes its effect on
extraction and rendering before the inert set is fixed.

**X5 — Kerned `TJ` is bound by item *runs*, and a run is collapsed with its
kern sum preserved.** Because the corpus kern is intra-word (§1.2), per-item
splicing cannot work: the user's word straddles items. Rule: the target bytes
must equal the exact concatenation of a contiguous item run `[i..j]`; the
splice replaces `[item_i.start, item_j.end)` with `(new) K` where `K =
Σ kerns strictly inside the run` (omitted when zero); the **string-advance
equality gate is unchanged** (`adv(new) == Σ adv(items)`, `plan.py:1285`).
Consumed advance is then identical by arithmetic, items outside the run and
the kerns bordering it are byte-identical, and downstream shows are unmoved.
**Probe P-B (2026-09-06, texttrace origins to 1e-6 + 300 dpi pixel diff):**
downstream deviation is exactly 0.0 for the two-number spelling
`[(new) K <border>]` in every case (Tc, Tz 80, Tw, hex item, Identity-H,
rotated Tm, continuation show with no positioning operator, run at array
end). Three conditions the implementation must obey: (a) **never merge `K`
into the bordering kern** — the merged spelling drifts by one float32 ulp
(7.6e-6 pt) whenever `Tz != 100`; (b) "equal string advance" is the full
consumed advance `_advance` already computes (`/Widths` sum + `Tc`·glyphs +
`Tw`·spaces) — equal width sums alone shift the tail by `Tc` per extra glyph;
(c) `K` is emitted even when the run is the array's last element (MuPDF
applies a trailing number; dropping it moves the next show), and only
`K == 0` is omitted. A stated consequence, not a defect: the replaced word
loses the pair kerning that belonged to its *old* letter pairs (0.06 pt on
the probe), exactly as any re-typeset word would; downstream and the word
gaps are untouched.
When the target contains spaces that the stream realises as kerns (no space
byte), the target is split at those spaces into tokens, each token must
match an item run exactly, and each run is collapsed independently with the
bordering word-gap kerns untouched — so the gap width cannot jump. Anything
else refuses `TJ_RUN_ALIGNMENT_UNPROVEN`. Growth still escalates to Tier 1
exactly as today (`_TIER1_ESCALATION_REASONS`). Per-item origins for the
binder's 0.5 pt origin test come from a cursor replay: `predict_glyphs`
(`glyph_boxes.py:267`) for CID fonts, and a sibling for simple fonts built on
`_advance` (`plan.py:221`). This supersedes the 2026-08-01 deferral at
`TODOS.md:455`: that deferral measured *byte-binding* survival (0.59 %) under
the whole-operand rule; run binding is a different rule, and its survival is
measured in S4 Step 0 before the gate is written.

**X6 — A word inside a string is a fragment splice, proven by re-lexing the
whole operand.** S5 binds a target whose bytes are a proper substring of one
item, disambiguated by the per-glyph origin from the same cursor replay, and
splices only those bytes with an advance-equal encoding. The literal-string
escape grammar makes decoded offsets ≠ raw offsets, so `pdf_lexer` gains a
decode-with-offset-map helper (octal, `\n`-style escapes, line
continuations); hex is two chars per byte; Identity-H fragments must start
and end on even decoded offsets. The proof re-lexes the *whole* post-splice
operand token, requires exactly one string token, and requires its decoded
bytes to equal `prefix + new + suffix`. `Tw` applies to byte 0x20 of a
single-byte code only (PDF 32000-1 §9.3.3), so a fragment's advance folds
`Tc` per code and `Tw` per 0x20 in the fragment — never per space character
of the replacement text. **Probe P-F (2026-09-06, 39 grammar cases judged by
MuPDF's own lexer through `pdf_lex`, extraction, replay and the repo
decoder):** MuPDF matches the spec on 39/39; the repo decoder matches MuPDF
on 36/39 — **it keeps a bare CR / CRLF inside a literal as raw 0x0D bytes
where MuPDF decodes one 0x0A** (`pdf_lexer.py:214-217`). That is a
pre-existing defect shared by `replay.py:368`, `verify.py:449` and
`glyph_boxes.py:225`; today it only fails closed (whole-operand byte
compare), but a fragment splice would compute offsets in a different space
from MuPDF's, so **S0 fixes the decoder red-first** and S5 builds the offset
map on the fixed decoder. Offset rule (token-relative): plain byte and
bare LF/CR → 1 raw byte; named/unknown escape → 2; octal → `1 + digits`
(greedy 1–3); bare CRLF → 2 raw bytes → one 0x0A; backslash-EOL continuation
→ zero-width, attach to a neighbour. Hex is **not** two chars per byte:
MuPDF skips whitespace (0x00/09/0A/0C/0D/20) inside `<…>` and pads an odd
final digit — the hex offset map is digit-aware, or hex items with interior
whitespace refuse `SUBSTRING_OFFSET_UNPROVEN`. Boundary hazard the proof alone does
not name: when the byte before the fragment is a **short octal escape**
(``, `)`) and the replacement starts with an octal digit, the naive
raw splice re-associates the digit (`(XQb)` → `(X/b)` renders `/`), so
the writer must emit the fragment's first byte as a 3-digit `\ddd` or widen
the range to re-emit the short escape in full — a named gate,
`SUBSTRING_OFFSET_UNPROVEN`, not a silent fix-up. No suffix-side hazard:
`encode_literal_string` never emits octal, raw EOL or a lone backslash.

**X7 — Type3 is a simple font whose metrics live in glyph space, and MuPDF
quantises them.** **Probe P-E (2026-09-06) refuted the naive formula:**
MuPDF stores a Type3 advance as an *integer* 1/1000 text-space unit,
`adv = trunc(float32(float32(a)·float32(w)) · 1000) / 1000 · Tfs + Tc (+Tw
for byte 0x20)`, all scaled by `Tz/100`. With `a = 0.001` and integer
`/Widths` the naive formula is exact (0/4096 deviations in a sweep, max
6e-6 pt); with fractional widths, or `a = 1/2048` (the corpus's second
Type3 shape, 2024/2048 widths fail), or pdfTeX-style scales (0.01, 0.012),
it is wrong by up to the truncation. Rule: admit a code only when the
float32 product `a·w·1000` is an integer (evaluate with struct-packed
float32 to mirror MuPDF), else `TYPE3_WIDTH_UNPROVABLE`; compute the advance
from the truncated integer. MuPDF reads only `FontMatrix.a` for the
advance (b, c, d affect rendering, not the cursor), so diagonality is a
*conservative* gate (spec-vs-MuPDF disagreement; other renderers), not the
load-bearing one. **Admission rule, stated so the corpus shape is not
refused by accident:** finite `a > 0` with integral `float32(a·w·1000)` for
every code the edit touches; `b == c == 0`; any finite non-zero `d` (the
corpus's dominant shape has `d = −0.001`, sign irrelevant to the cursor);
`a <= 0`, non-finite, or non-diagonal → `TYPE3_FONTMATRIX_UNSUPPORTED`. The
advance is computed over **encoded bytes** with `Tw` per 0x20 *byte*; the
simple-font `_advance` (`plan.py:236`, `text.count(" ")`) is safe only for the
three standard encodings and is not reused for Type3. **Duplicate gate:** a
Type3 capability has `cid is None`, so the exact arm never runs and the gate
would fall to the declared-advance target core that `PITFALLS.md:2893`
records as unsound on the target side; a charproc may paint anywhere. S6
therefore refuses any Type3 target that has a same-bytes twin
(`DUPLICATE_SOURCE_PAINTER`, "cannot prove target placement") — bounding
target ink by `/FontBBox × FontMatrix × Tfs` is a later, separately proven
step, not assumed. The V0d `target_bbox` fallback quad (`plan.py:1220-1232`,
−0.35/1.0 em) is likewise unproven for charprocs: S6 derives it from
`/FontBBox` when present and refuses otherwise. Every
advance oracle in the tests must read glyph **origins** (texttrace/rawdict),
never the texttrace bbox width, which carries the unquantised value.
Without `/ToUnicode` MuPDF extracts `/Differences` names through the AGL
and falls back to the code value for unknown names — the reverse map goes
through `/ToUnicode` only and never trusts extraction. Encoding is `/Differences` names (mandatory for Type3);
the reverse map char → code goes through `/ToUnicode` (the existing strict
CMap parser, `cid_fonts.py:412`, generalised to a 1-byte codespace) and must
be unique. Glyph presence = the code's `/Differences` name is a `/CharProcs`
key. Ink is unbounded by any outline oracle (a charproc is arbitrary content)
so `_painter_glyph_ink` answers `None` and the duplicate gate keeps its reach
bound. The same font resource is reused, so rendering is identical by
construction. New `TYPE3_*` codes; `FONT_TYPE3` is emitted only for a Type3
that fails the shape above.

**X8 — Zero-corpus classes stay refused by name.** Modes 1/3/4-7, `'`/`"`,
`rise`, `/Differences`, symbolic, Identity-V, CFF descendants, non-Identity
CMaps: each keeps (or gains) a **named** refusal branch and a registered
slice with the measurement that would open it (§8). Admitting a shape no
document exercises adds an unproven verification surface for zero yield —
the same reasoning as D7.

---

## 4. Slices, in order

Order (revised after the critic's ordering verdict): **S0 → S1 → S2 → S7 →
{S4, S5} → S6 → S3 → docs.** S1 and S2 are measured together (§1.3 item 1).
S7 comes right after S2: one gate line, one pin, no new grammar, 334 shows.
S4 and S5 are ordered by the two read-only Step 0 measurements S0 runs (run
binding survival vs fragment survival); the funnel's
`target_reconstruction_unverified` 129 + `no_source_match` 56 (15 % of
samples) is the population S5 addresses and S4's is the 65 % kerned share of
the 402-page fixture. S3 goes **last** among the engine slices: smallest
yield (141 Office + 9 CAD shows), riskiest (a new ink bound at a false-safe
gate), and it changes two existing p4b2 pins (named below) — its pivot
conditions are unchanged. Each slice is a separate commit series and
ends with the acceptance re-measurement of X2.

### S0 — Evidence and instruments (no engine change)

- Wait for / append the CAD-drawing census (§1.4). Re-run E1–E8 of the
  original plan on this machine (its Step 0).
- Promote the shape probe to `scripts/census_show_shapes.py` (read-only,
  counts only, positional doc index, output is always JSON; mirrors the privacy contract
  of `audit_tier_coverage.py`). Add `--pages N` sampling for the 402-page
  fixture. Pin with a small test on a synthetic 3-show page.
- Fix the funnel artefact: `measure_tier_funnel.py` must pass a
  `DocumentFontRegistry` to `bind_source_text` so CJK targets stop counting
  as `undecodable_target` (today 623/1265 of the sample is mislabelled).
- Fix `decode_literal_string` (`pdf_lexer.py:214-217`) red-first: a bare
  CR and a bare CRLF inside a literal decode to one 0x0A (PDF 32000-1
  §7.3.4.2; P-F measured MuPDF doing exactly that). Chokepoint fix — replay,
  verify and glyph_boxes inherit it; pin with the three divergent cases
  (`(a<CR>b)`, `(a<CRLF>b)`, `(a<LF><CR>b)`) against `page.get_text`.
- Fix `audit_tier_coverage.py`'s mirror predicates (§1.4): call
  `admit_show_wrappers` and `admission_verdict` instead of folding
  `mc_depth != 0` / `trm_uniform_scaled` into `unsupported_text_state`.
- Fix `measure_tier_funnel.py`'s **plan stage** too: `_identity_plan_survival`
  (`:339-364`) is a stale mirror (operator gate first, `mc_depth != 0 →
  UNSUPPORTED_TEXT_STATE`, never calls `admit_show_wrappers`) and
  `_bind_against_replay` (`:277-282`) refuses every non-uniform TRM. Replace
  both with the production calls (`bind_source_text(..., registry=,
  resolved=)` over a once-per-page `resolve_replay`, then the classifier's
  gates through a `_classify_common`-equivalent or `TieredCommitEngine.prepare`
  on an in-memory copy, as `measure_type0_funnel.py:83-1177` already does).
  Add a parity test: a synthetic `/P <</MCID 0>> BDC … [(x)] TJ` page must
  report the same reason from the funnel as from `prepare_plan`.
- Why a new census script rather than extending `measure_type0_funnel.py`:
  that funnel is Type0-only by contract; the shape census counts every font
  kind and every operator. Cross-reference the two in both docstrings.
- Run the two S4/S5 Step 0 measurements (read-only) so §4's order between
  them is set by numbers before either is designed.
- Re-run tandem E1–E8 (still owed by that plan's Step 0).
- **S0-b (production bug found by the S4/S5 Step 0 measurement, verified
  directly 2026-09-06):** `DocumentFontRegistry.capability()` and
  `page_capabilities()` (`fonts.py:701-729`) select `page.get_fonts(full=True)`
  entries by resource name with "last entry wins" and never check the
  referencer (`entry[6]`, 0 for the page's own `/Resources`, an xref for a
  Form XObject's own). On the 402-page fixture page 7, `capability(page,
  "F0")` returns the XObject-local `F0` (TrueType/WinAnsi, xref 3462,
  referencer 440) while the page's own `/Resources/Font/F0` is xref 487
  (Type0/Identity-H); 59/60 sampled pages carry such a collision. A page
  stream's show can only mean the page-scoped resource (replay never enters
  XObjects), so the fix is a chokepoint filter: both lookups consider only
  entries with referencer 0 and return `None` (→ `FONT_FACE_UNAVAILABLE`)
  when the name exists only in an XObject scope. Red test: a synthetic page
  whose `/Resources/Font/F1` is Helvetica and whose Form XObject's own
  `/Resources/Font/F1` is a different simple font → `capability(page, "F1")`
  must return the page's xref; today it returns the XObject's. Then the
  duplicate-painter gate's `_same_font_object` and the census scripts inherit
  the fix. Register in `docs/PITFALLS.md` under its own entry.
- Docs: amend `TODOS.md` T16-4 (this program), `PITFALLS.md:3001-3002` and
  `:2812` per the original Step 0, plus new pitfalls: *the operator gate
  masks every gate behind it — a funnel that reports one code is not a
  funnel*; *a literal-string bare EOL is one 0x0A, not the raw bytes*; *an
  audit that mirrors a gate goes stale the day the gate moves*. **Done 2026-09-06 S0 fold 2:** PITFALLS index regenerated (368 entries); TODOS and tandem plan Step 0 scope note amended.

### S1 — Single-item `TJ` + render-mode ladder + pen proof (= original plan Phase A, Steps 1–12)

Spec: `plans/task16-4-tandem-bold-commit.md` §Affected modules, §Fail-closed
gates, Steps 1–12, verbatim. Amendments from this program (each a red test
first):

- **Second emission site (blocker).** The CID leg's `string_kind != "hex"`
  refusal (`plan.py:1064-1074`) must admit `string_kind == "array"` when the
  single inner item re-lexes as a `HEXSTRING` (per-item kind from the
  `tj_items` sibling) and keep refusing a *literal* inner item under the
  hex-only scope. Re-pin `test_rotated_tj_array_target_keeps_the_tj_scope_gate`
  (`test_text_commit_trm_admission.py:825-837`) to ADMITTED, otherwise the
  second site masks the first under the same code (`PITFALLS.md:1997`).
  Update the mirrored stage at `measure_type0_funnel.py:1140-1143`.
- **Leading kern before the single item.** `[-3000 (Hello)] TJ` displaces
  the ink from `origin_user`, which `_painter_core_quad` (`plan.py:628-636`)
  and the `target_bbox` fallback both assume is the ink origin; simple-font
  targets never reach the exact arm, so the displaced core would be the
  only bound — a false-safe. S1 refuses a single-item `TJ` whose item is
  preceded by any kern with its own code `TJ_LEADING_KERN_UNPROVEN` (folding
  the cumulative pre-item kern into core, exact-arm placement and fallback
  quad is S4's cursor-replay work). Red test: the leading-kern page plus a
  twin at the displaced position must be refused.
- Inner-item re-lex failure gets its own code `TJ_ITEM_RELEX_FAILED` (the
  tandem table reused `NOT_SINGLE_LITERAL_TJ`; `dto.py:52-56` forbids that).
- The tandem gate table's "mode 3 → `UNSUPPORTED_TEXT_STATE`" row and D7 are
  amended to "refused until S7".
- `PreparedEdit.splice_kind = "string_token"` is introduced here (X3),
  defaulted so every hand-built `PreparedEdit` stays valid; `_content_token`
  folds it.
- `TJ_MULTI_ITEM_ARRAY` is emitted for multi-item arrays **until S4**, which
  replaces that emission site (the code stays declared with a retirement
  note; codes are never renamed).

Pins this slice flips (each re-pinned to its new measured outcome, never
deleted): `test_planner_rejects_tj_array_pages` (`test_text_commit_tier0.py:189`
— `insert_text` writes single-item `[<…>] TJ`, so it may now COMMIT),
`test_text_commit_shadow_mode.py:108` (`not_single_literal_tj` in the shadow
log), `test_planner_rejects_nonzero_render_mode` and the `2 Tr` rows of
`test_text_commit_structural_gates.py:190-268`,
`test_positive_hscale_does_not_mask_multi_item_tj_gate` (`:312-326`, moves to
`TJ_MULTI_ITEM_ARRAY`), `test_literal_string_type0_tj_refused_hex_only_scope`
(`test_text_commit_cid_hex_tj.py:1442-1452`, unchanged — the hex-only scope
survives), and the trm_admission pin above.

**Extended 2026-09-08 (S1 review fold):** five more modules the reviewers
found the original list did not name, each because its fixture-building
helper relied on a single-item `TJ`/`[<hex>] TJ` refusing at the operator
gate to reach the behaviour under test, and S1 admitting that shape let
every one of their tests commit at Tier 0 instead:
`test_text_commit_consent_flow.py` (`_tj_array_stream` reshaped from the
now-admitted single-item shape to a genuine MULTI-item array, so the
legacy-fallback/consent path under test is still reached);
`test_text_commit_degrade_visibility.py` (same reshape, same reason — the
degrade path it exists to test); `test_text_commit_default_engine_ux.py`
(the same hex codes split across two array items, keeping the page
otherwise ordinary, so its three degrade/consent pins still reach legacy);
`test_type0_vocabulary_counterfactual.py` (`test_priority_units_use_per_font_
corpus_union_rates`, re-pinned TWICE — first when S1 let four `[<hex>] TJ`
shows pass the funnel's operand-scope mirror, doubling the baseline/
augmentation numerators 8→16 / 20→40 while `tj_array_show_equivalents`
stayed at 4; then again under S1 review L3, which fixed the funnel's
double-count so those four shows are counted once, in the baseline, giving
`tj_array_show_equivalents == 0` / `tj_array_numerator == 0` with the 16/40
baseline unmoved — the proof the shows had been counted twice);
`test_glyph_overlap_census.py` (S1 review L3: three shapes re-pinned —
a single-item `TJ` that used to book `tj_array_only` now books `all_gates_
pass` instead; a shape whose operand source moved from `80 Tz [<hex> -100]
TJ` to a leading-kern spelling so it still measures a genuine refusal
instead of the now-admitted trailing-kern shape; and a one-hex-item
TRAILING-kern show that no longer loses at `not_single_hex_tj` and now
reaches the glyph-loss measurement it was meant to exercise).

**The fixture-pins module's measured outcome (2026-09-08, new file, part of
this slice):** `test_scripts/test_text_commit_s1_fixture_pins.py` is the
module the plan's own Steps 0/12 predicted (§4 S1 "Acceptance adds"),
promoted to a standing pin. Its headline finding: the tandem plan's Step 12
predicted `seq 7/11/15` → ACCEPTED and `seq 49/50/51` → `duplicate_source_
painter`; neither is reachable on the real CAD fixture. All ten single-item
bold targets (the nine `Tr 2` shows plus the one simple-font show, `p0
seq=2`) sit inside a struct-content marked-content wrapper, so every one
refuses `mc_wrapper_not_pure_layer` with `"struct_content"` in the detail —
the S2 gate, not S1's render-mode ladder or the duplicate-painter gate.
Every refusal is confirmed to leave the two read pages byte-identical. See
the tandem plan's Step 12 amendment and this plan's §1.2 amendment for the
full write-up.

Acceptance adds: funnel plan-survival on office-report-23p moves from
`not_single_literal_tj` 245/245 to `mc_wrapper_not_pure_layer` ≈ 245/245
(the S2 premise, demonstrated not assumed); CAD fixture pins of Step 12.

### S2 — Render-inert marked content

Files: `marked_content.py` (`admit_show_wrappers`, `classify_wrapper`,
`update_marked_content_dependencies`), `dto.py`, `inspect.py` (fingerprint
fold only), tests `test_text_commit_mc_admission.py` (+ new file
`test_text_commit_mc_struct_admission.py`).

Gates (fail closed, one code per independent gate):

| condition | code |
|---|---|
| wrapper class ∈ {`struct_content`, `artifact`, `bmc_bare`} and every enclosing wrapper individually admissible | admitted |
| property dict carries a key outside the inert set (`MCID`, `Lang`; Artifact: `Type`, `Subtype`, `BBox`, `Attached`) | `MC_WRAPPER_NOT_PURE_LAYER` (detail: class slug + `key_outside_inert_set`) |
| `ActualText` / `Alt` anywhere in the stack | `MC_WRAPPER_NOT_PURE_LAYER` (detail names the class) — unchanged code, new reason text |
| named Properties target unreadable / not a dict | new `MC_PROPERTIES_UNRESOLVED` |
| splice range not strictly inside every wrapper span | `MC_SPLICE_CROSSES_WRAPPER_BOUNDARY` (unchanged) |
| malformed pairing, EMC underflow | `MC_MALFORMED_PAIRING` (unchanged) |

Code scope, fixed now so the red contract can pin it:
`MC_PROPERTIES_UNRESOLVED` covers a **named** target that is missing,
unreadable or not a dict; the four existing `props_unresolved` causes that are
about OCG visibility (missing name under `/OC`, `/AS` usage rule, bogus
`/BaseState`, unresolvable `/OFF`; `test_text_commit_mc_admission.py:584-628`)
stay under `MC_WRAPPER_NOT_PURE_LAYER` unchanged. `classify_wrapper` must
expose the **full key set** of an Artifact or direct-dict target before the
inert-set check (today `tag == "Artifact"` short-circuits and the direct-dict
branch keeps only three keys).

Pins this slice flips, by name: `test_artifact_wrapper_is_rejected`,
`test_struct_content_mcid_wrapper_is_rejected`, `test_bare_bmc_wrapper_is_rejected`
(→ admitted); `test_mc_reject_reason_constants_exist_verbatim` (`:127-140`,
four codes → five) and the privacy sweep's `result.reason in _ALL_MC_CODES`
(`:560`); `test_planner_rejects_marked_content_target`
(`test_text_commit_structural_gates.py:163-185`); the struct_content pin in
`test_text_commit_tier1_slice1.py:1331-1335`.

Steps (red first): (0) probe StructElem-level `/ActualText`/`/Alt` via
`/StructParents` (X4) and census the property keys Office emits on `/P`,
`/Span`, `/Artifact` across the three Office fixtures — the inert set is
fixed from that census, fail-closed; (1) parametrised admission tests on
synthetic Identity-H fixtures wrapped by `wrap_content_in_marked_content`
for `/P <</MCID 0>>`,
`/Artifact <</Type/Pagination>>`, bare `/Span BMC`, nested struct-in-OC —
all `mc_wrapper_not_pure_layer` today; (2) refusal tests for
`ActualText`, `Alt`, an extra key, an unreadable named target; (3) proof
obligations 1–5 replicated (encode round-trip, save→reopen extraction
equality, render-hash equality wrapped vs unwrapped, splice-inside guard,
fingerprint staleness on a named target edit → `STALE_PLAN`); (4)
implement; (5) census on office-report-23p: `mc_wrapper_not_pure_layer` → 0,
plan survivors > 0 for the first time; record the new dominant code.

### S3 — Stroke ink bound at the duplicate gate (= original plan Phase B, Steps 13–15) — last engine slice

Verbatim from the original plan, including its pivot condition ("Step 13
cannot be made red ⇒ Phase B does not ship"), with one amendment the critic
forced: the tandem pivot "any `test_p4b2_admission_gate.py` pin requires
editing ⇒ revert Phase B" is **self-contradictory** with Step 15, because
admitting mode 2 into `_painter_glyph_ink` necessarily changes two rows that
pin mode 2 to the reach path:
`test_non_fill_render_mode_twin_falls_to_the_reach_path[2]` (`:423-434`,
asserts `GLYPH_INK not in detail`) and
`test_a_stroked_twin_under_a_singular_text_matrix_is_refused[2]` (`:548-568`,
pins "cannot prove disjoint placement"). S3 names exactly these two as the
pins it changes (mode-2 row → glyph-ink refusal with the conservative pad;
singular-Tm mode-2 row → refused by an explicit **rank-deficient text-matrix
check before the pad is trusted**, its own detail — D6 covers a degenerate
`loca` span, not a degenerate mapping, and a pad on a collapsed box must
never be what makes a twin "boundable"). Any *other* p4b2 pin going red keeps
the revert rule.

### S4 — Kerned `TJ` run binding and kern-sum collapse (X5)

Files: `inspect.py` (`bind_source_text`: run candidates + per-item origin),
`glyph_boxes.py` (`tj_items` sibling with absolute offsets; simple-font
cursor replay), `plan.py` (`_classify_common` TJ branch, `_build_tier0`
run splice, `_content_token`), `verify.py` (`_target_operator_failure`
`"tj_run"` arm), `dto.py`, `patch.py` **no change** (the run replacement is
one `StreamReplacement`), `preview.py` no change.

Step 0 (measure before designing the gate): run-binding survival on
office-report-23p and the 402-page fixture — for every word run and line
sample, does the target align to an item run under X5's rule? Record the
rate and the top three failure shapes. **Pivot:** if survival < 20 % of
kerned shows, stop and re-derive the rule from the failure shapes before
writing any code.

**S4 Step 0 measured 2026-09-06:** aggregate 528/1094 = 48.3 % (PASS). Per
fixture: office-report-23p 21/22 = 95.5 % (untested: 70 no-target, 186
multishow-only); the 402-page fixture 489/1047 = 46.7 % (untested: 1541
no-target, 935 multishow-only); CAD-drawing fixture 18/25 = 72.0 % (untested: 409
no-target, 42 multishow-only). Top three failure shapes (aggregate, 1094
tested): `item_contains_partial_word` 206, `target_not_in_show_text` 188,
`straddles_boundary_with_space_byte` 170; each fixture individually passes
its 20 % pivot. Survival pivot cleared; S4 goes first.

Gates:

| condition | code |
|---|---|
| target aligns to one item run (or to token-wise runs across kern gaps) | admitted |
| no alignment / ambiguous alignment | `TJ_RUN_ALIGNMENT_UNPROVEN` |
| run re-lex fails, kern non-finite, kern sum not representable in 6 decimals | `TJ_KERN_SUM_UNPROVEN` |
| `adv(new) != Σ adv(items)` | `ADVANCE_MISMATCH` (unchanged; Tier 1 escalation unchanged) |
| two candidate runs within 0.5 pt | `AMBIGUOUS_MATCH` (unchanged) |

Proof: `"tj_run"` arm re-lexes the replacement as `STRING [NUMBER]`, checks
the number equals the recorded kern sum byte-for-byte, and checks the
post-splice array still lexes `[` … `]` with the untouched items
byte-identical to pre-state. Token folds run offsets and the kern sum.

Duplicate-painter gate for a run target (the plan was silent; the critic is
right): twin **candidacy stays whole-operand** (`candidate.decoded_bytes ==
target.decoded_bytes`, `plan.py:622-627`) — a same-line twin whose whole
bytes equal the target's must still be refused when the edited run overlaps
it (red test). The **target core** becomes the run's cursor extent from the
same cursor replay, not the show origin + show advance; the exact arm places
`cids=` as the original items with the run substituted in place, not as one
item at the show origin (`plan.py:498-502`). The `target_bbox` fallback quad
follows the same cursor extent.

Lifecycle: the CAD page-0 `seq 9/13` pins that S1 set to `TJ_MULTI_ITEM_ARRAY`
move to their measured post-S4 code; `TJ_MULTI_ITEM_ARRAY` is retired with a
migration note in `dto.py` (declared, no emission site).

Red tests: `[(He) -5 (llo)] TJ` → target "Hello" admitted, stream becomes
`[(Jello) -5] TJ` (helv: same widths — pick letters accordingly), bytes
outside the run identical; `[(Hello) -250 (World)] TJ` → target "Hello World"
admitted token-wise, the `-250` byte-identical post-commit, rendered gap
pixel-identical at zoom 64; a target spanning half an item refuses
`TJ_RUN_ALIGNMENT_UNPROVEN`; every refusal byte-identical.

### S5 — Fragment splice inside one string item (X6)

Files: `pdf_lexer.py` (`decode_literal_string_with_offsets`), `inspect.py`
(fragment candidates, origin from cursor replay), `plan.py`, `verify.py`
(`"string_fragment"` arm), `dto.py`, tests.

Step 0: measure, on office-report-23p and prose-1p, the share of word-run
samples whose bytes are a proper substring of exactly one item at the
expected origin. Pivot: if < 10 %, defer S5 behind S6.

**S5 Step 0 measured 2026-09-06:** aggregate fragment rate 635/3160 = 20.1 %
(PASS aggregate). Per fixture: office-report-23p 7/82 = 8.5 % (FAIL, pivot
< 10 % — defer S5 behind S6 on this fixture alone); the 402-page fixture
359/1148 = 31.3 % (PASS); CAD-drawing fixture 269/1930 = 13.9 % (PASS). 909/3160
(28.8 %) measured word-run targets are covered by neither rule (not equal, not
a proper substring, not a multi-item span). Two targets per show's maximum:
27 % of kerned shows had no clean single-show target. Aggregate pivot cleared;
S5 **follows S4** because CJK-only fixture (the CJK office-report fixture) fails its individual
pivot at 8.5 %; S5 design may need re-derivation for CJK or deferral if S4
proves CJK-only limitation.

Gates: `SUBSTRING_OFFSET_UNPROVEN` (escape map cannot place the fragment,
short-octal boundary, hex interior whitespace), `SUBSTRING_CODE_BOUNDARY`
(2-byte misalignment), `SUBSTRING_ORIGIN_AMBIGUOUS` (two occurrences inside
0.5 pt), else the existing ladder. Proof per X6. Duplicate-painter gate as in
S4: whole-operand twin candidacy, fragment cursor extent as the target core,
in-place substitution for the exact arm's `cids=`.
Red tests include a literal with an escaped delimiter *before* the fragment
(offset map load-bearing), a hex item, an Identity-H item, and a fragment at
the item's first and last byte.

### S6 — Type3 (X7)

Files: `fonts.py` (`_build_capability` Type3 branch → `Type3Capability`;
`_type3_evidence_digest` (`:529-547`) must fold the **whole closure** — font
dict canonical, `/Differences` target, every `/CharProcs` stream, `/Resources`,
`/ToUnicode` stream — today it folds descriptor flags only), `inspect.py`
(new `_update_type3_dependencies` beside `_FONT_DEPENDENCY_KEYS` (`:129-139`)
folding the same closure into the page fingerprint; red tests: mutate a
charproc / `FontMatrix` / `ToUnicode` between prepare and commit → `STALE_PLAN`,
and the registry rebuilds the capability), new
`model/text_commit/type3_fonts.py` (readers: FontMatrix, Differences,
CharProcs, Widths; 1-byte ToUnicode via `parse_tounicode_strict`,
`cid_fonts.py:503`), `plan.py` (advance + encoding through the capability's
own methods; same-bytes twin ⇒ refuse per X7; `target_bbox` from
`/FontBBox`), `dto.py` (`TYPE3_FONTMATRIX_UNSUPPORTED`,
`TYPE3_ENCODING_UNPROVEN`, `TYPE3_TOUNICODE_MISSING`,
`TYPE3_TOUNICODE_UNPARSEABLE`, `TYPE3_TOUNICODE_AMBIGUOUS`,
`TYPE3_CHARPROC_MISSING`, `TYPE3_WIDTH_UNPROVABLE`), fixture builder
`test_scripts/type3_fixture_builder.py` (hand-authored charprocs — a square
and a bar — so ink is deterministic), tests.

Step 0: sweep the corpus fixture's **actual** `/Widths` and sizes through
the float32 integrality rule (P-E swept integer widths at `Tfs 10`, `a =
0.001` only) and count the `1/2048` font's shows.

Red matrix: admitted shape commits at Tier 0 with byte-identical stream
outside the operand and V0d identity; **the corpus shape with `d < 0` is
ADMITTED**; each gate above red-then-green; non-diagonal FontMatrix refused;
a Type3 target with a same-bytes twin refused "cannot prove target
placement"; a code whose name is absent from
CharProcs refused; the complex-layout-2p fixture pin: 1621 shows change
code from `font_type3` to their true next gate (recorded, not predicted).

### S7 — Invisible text (`3 Tr`)

Files: `plan.py` (render-mode ladder from S1 admits `{0, 2, 3}`;
`_painter_glyph_ink` returns `[]` — "proven to paint nothing" — for mode 3;
`target_bbox` halo unchanged, it only bounds V0c/V0d), `dto.py` (no new
code: mode 3 is admitted, modes 1/4-7 keep their named refusals), tests
`test_text_commit_stroke_admission.py` (S1's ladder file) gains the mode-3
rows.

Why sound: a mode-3 show paints no ink, so the duplicate-painter gate has
no target ink to protect and no twin the new operand could damage; V0d
raster identity holds trivially; V0c "replacement extractable" still holds
(invisible text extracts). The one hazard is a mode-3 target with a
*visible* same-bytes twin at the same place (OCR text over a rendered
glyph): editing the invisible layer is legitimate and paints nothing, so
the gate must not refuse it — pin that as a red test, not an assumption.

Step 0 (probe P-G, not yet run — the critic is right that "invisible text
extracts" was asserted, not measured): `3 Tr (Hello) Tj` → `get_text`,
rawdict and words before and after an offset-faithful splice; the same
under a struct wrapper (Office OCR exports); a visible same-bytes twin over
it. If mode-3 text does **not** extract, V0c fails closed and S7's yield is
zero — stop and register instead. Note the app itself writes mode-3 text
(`apply_ocr_spans`, `test_ocr_e2e.py:147`), so S7 also changes what the
editor does to its own OCR layers; say so in ARCHITECTURE.

Pins this slice flips: `test_text_commit_tier1_slice1.py:1338-1358` (mode 3 →
`UNSUPPORTED_TEXT_STATE` at `max_tier=1`); the tandem gate-table row amended
in S1.

Red tests: synthetic `3 Tr (text) Tj` page → today `unsupported_text_state`;
after: Tier 0 COMMITTED, pixmap byte-identical before/after (the whole
page, not only outside the halo), `get_text` shows the replacement; a
mode-3 target with a visible twin admitted; mode 3 with `rise != 0` still
refused; every refusal byte-identical. Acceptance: on the 402-page fixture
the 334 shows change code from `unsupported_text_state` to their true next
gate (recorded).

### S7a — 8-bit simple encodings (register-now, open on first corpus hit)

Full Standard/WinAnsi/MacRoman code tables in `fonts.py`, reverse map with
uniqueness proof, `missing_glyphs` unchanged. **Do not implement until a
fixture exercises it**; the census currently shows 0. Kept in the plan so the
next reader does not re-derive the design.

### S10 — Inline /Annots dictionaries refuse with a stable code (I0d)

**Problem.** PyMuPDF 1.27.1 `page.annot_xrefs()` reports an annotation that the
page lists as an inline dictionary (no indirect reference) as xref 0, and
`page.annots()` then raises `AttributeError: 'NoneType' object has no attribute
'm_internal'`. The engine called `annots()` in `capture_page_state`, so the error
escaped `TieredCommitEngine.prepare` (and `commit`, and the plan preview) instead
of returning a refusal. V0b's "annotations untouched" proof is keyed by xref, so
it cannot identify such an annotation either; two inline dictionaries also
collided on `rects[0]` in `page_fingerprint`.

**Files.** `model/text_commit/inspect.py` (`InlineAnnotationError`,
`AnnotationListOutOfSync`, `_UNLISTED_ANNOT_KINDS`, `_inline_kind_listed`,
`_is_listed_inline`, `require_indirect_annotations`, `_read_annotation_entries`,
`annotation_entries` strict, `_annotation_entries` tolerant, `_widget_entries`,
`page_has_widgets_or_signatures`), `dto.py`
(`RejectReason.ANNOTATIONS_NOT_INDIRECT`), `plan.py` (gate in `prepare_plan`),
`engine.py` (backstop in `prepare`, conversion in `commit`), `preview.py`
(backstop), `verify.py` (three call sites use the strict reader),
`view/text_edit_reasons.py` (sentence, not rebuildable).

**Why sound.** Fail closed and zero mutation: the gate runs before any geometry
read; the backstops run before any splice; the commit refusal runs before
`apply_patchset`. Pages with only indirect annotations, and pages whose only
inline entry is an unlisted kind (Link, Popup; Widget is refused upstream
already), take byte-identical paths: `annotation_entries` equals
`tuple((a.xref, tuple(a.rect)) for a in page.annots())` (test 6) and the
fingerprint is unchanged. `InlineAnnotationError` subclasses `Exception` on
purpose, so the existing `(RuntimeError, ValueError, FzErrorBase)` handlers do
not swallow it under a wrong code. `page_fingerprint` never raises it. The
commit race (annotation added between prepare and commit) returns
`CommitStatus.FAILED` with chain `("tier0:annotations_not_indirect",)`, not
`STALE_PLAN`, since a re-prepare refuses identically. `verify.py` V0b post-read
is not converted: unreachable after a passing pre-capture, and the engine's
revert-then-re-raise covers it.

**Rebuild button hidden, model not gated.** `rebuild_offered_for("annotations_not_indirect")`
is False: the rebuild's own annotation safeguard (`_save_overlapping_annots`)
gets the same `AttributeError`, warns and snapshots nothing. That is a
conservative fail-closed choice, not a shown loss: a probe with the production
redaction flags kept inline Square, Text and FreeText annotations. The model
never checks this code: `pdf_text_edit.edit_text` sends any tiered refusal with
`allow_rebuild=True` (the consented cross-page move included) to the legacy
rebuild, and the `pdf_model.py` hard-reject boundary stays widgets and
signatures only. A restyle, drag, delete or multiline edit on such a page is
refused by an earlier, rebuildable gate (`style_override_present`,
`geometry_override_present`, `empty_replacement`, `multiline_replacement`).
Extending the hard reject is an owner decision (TODOS.md, T16-4).

**Fix round 1.** Neither annotation reader calls `page.load_annot` any more:
it walks the same list as `first_annot`, so it cannot find an xref the walk
missed and raises a bare `Exception` no handler names (a page handle held
across an `/Annots` write). The strict reader raises `InlineAnnotationError`
for an unreachable xref; the tolerant one gives it a `(0, 0, 0, 0)` rect. The
strict reader is now the detector followed by the tolerant reader (one walk
implementation). Unknown-subtype inline entries are skipped by the walk, as
`annot_xrefs()` does.

**Audit (`rg -n "annots\(\)|annot_xrefs|first_annot" model/`, as landed).**

| Site | Call | Verdict |
|---|---|---|
| text_commit/verify.py `PreStateBaselineCache.capture` (preview) | `page.annots()` | fixed by chokepoint (`annotation_entries`); converted at preview.py |
| text_commit/verify.py `capture_page_state` | `page.annots()` | fixed by chokepoint; converted in engine.py `prepare` and `commit` |
| text_commit/verify.py V0b post | `page.annots()` | fixed by chokepoint; unreachable after pre-capture; engine revert+re-raise unchanged |
| text_commit/inspect.py `capture_annotation_parent_refs` | `page.annots()` | fixed by chokepoint (raises typed); no production caller |
| text_commit/inspect.py `_annotation_entries` | `annot_xrefs` + `first_annot`/`next` | fixed: same kind filter, tolerant, xref-0 rects in walk order (collision gone); fingerprint stays total |
| text_commit/plan.py `prepare_plan` | `annot_xrefs` (new) | the primary refusal gate |
| text_commit/inspect.py `page_has_widgets_or_signatures` | `page.widgets()` | fixed in round 2: `annot_xrefs()` kind check, loads no widget. Round 1 called this row guarded; it was not for a stale handle (`page.widgets()` raises a bare `Exception`, named by no handler) |
| text_commit/inspect.py `page_fingerprint` widget fold | `page.widgets()` | fixed in round 2: `_widget_entries` (tolerant `first_widget`/`next` walk), same order and values on 99 widgets of the test corpus |
| edit_commands.py `_page_xref_layout` | `annot_xrefs` | out of text-commit scope: identity tuple only, never loads an annot; guarded; xref-0 entries compare stably |
| pdf_object_ops.py `_page_annots` | `page.annots()` | already guarded (pre-existing `except Exception` returning `[]`; not touched) |
| tools/annotation_tool.py `_find_annotation` | `first_annot`/`next` | out of scope: rejects `xref <= 0` first; the walk does not raise |
| tools/annotation_tool.py `get_all_annotations` | `page.annots()` | out of scope, unguarded, raises on inline shapes: TODO registered |
| tools/annotation_tool.py `toggle_annotations_visibility` | `page.annots()` | out of scope, unguarded, raises: TODO registered |
| tools/annotation_tool.py `_save_overlapping_annots` | `page.annots()` | already guarded (warning, `[]`); the reason rebuild is not offered |
| tools/annotation_tool.py `_save_overlapping_links` | `annot_xrefs` | already guarded |
| tools/annotation_tool.py `_page_annot_identities` | `annot_xrefs` | already guarded |

**Pins flipped.** Only `test_text_commit_rebuild_action.py`: the explicit
`rebuild_offered_for(code) is False` tuple gains `annotations_not_indirect`
(its `vars(RejectReason)` loop already demanded a sentence of its own).

**Tests (red first).** New pure file `test_scripts/test_text_commit_direct_annots.py`
(26 pytest items after round 2; 17 at first landing): prepare refuses shapes A (`[inline]`), B (`[inline, x 0 R]`), F
(indirect array holding an inline dict) with zero object-table mutation; controls
C, D (indirect) and E (inline Link) still commit; commit race; prepare and
preview backstops with the plan gate bypassed; strict and tolerant reader
parity; fingerprint tolerance and distinction. Zero mutation is asserted on the
exact object table, never on `tobytes()` (its trailer `/ID` is unstable).

**Fix round 1 red runs (recorded here because the scratch report is not tracked).**
`test_unreachable_listed_xref_never_leaks_a_plain_exception` failed with
`Exception: xref 7 is not an annot of this page` before the `load_annot`
fallback was removed; `test_tolerant_reader_skips_unknown_subtype_inline_entries`
got `[100.0, 300.0]` instead of `[300.0, 350.0]` before `_inline_kind_listed`
was shared with the walk. 19 passed afterwards.

**Fix round 2.** (a) The widget list has the same stale-handle disagreement
as the annotation list: `page.widgets()` raises a bare `Exception` ("xref N
is not a widget of this page"; xref 0 for an inline widget) when a handle is
held across a by-xref /Annots write. Red: both new stale-widget cases failed
with exactly that. `page_has_widgets_or_signatures` now reads `annot_xrefs()`
kinds (no widget loaded) and `page_fingerprint` folds `_widget_entries`.
(b) `AnnotationListOutOfSync(InlineAnnotationError)` separates "a listed
indirect xref the handle cannot load" (a stale handle) from "an inline
dictionary" (a page shape): `engine.prepare` and the preview map it to
`verification_failed`, `engine.commit` to `STALE_PLAN` (before
`apply_patchset`, zero mutation), never to `annotations_not_indirect`, whose
sentence would be false. A real `commit` cannot reach it today (its
`_build_scratch_copy` serializes first, which resyncs MuPDF's list, and a
probe gave `STALE_PLAN` from the existing staleness check), so the mapping is
pinned by patching `capture_page_state` / `PreStateBaselineCache.capture`.
(c) `test_text_commit_structural_gates.py` gained three order cases (inline
alone -> `annotations_not_indirect`; widget + inline -> `signed_or_widget_target`;
inline + unprovable frame -> `annotations_not_indirect`); each fails under the
matching mutation of the gate position.

### Docs slice (every slice contributes; this closes it)

`docs/ARCHITECTURE.md` §10.1: new splice grammars and proof dispatch, new
codes, run/fragment binding, Type3 capability, inert marked content.
`docs/PITFALLS.md`: one entry per gotcha found (candidates already known:
operator gate masks the funnel; `Tw` is a byte-0x20 rule, not a space-char
rule; kern sum must be re-emitted, not dropped; ActualText is an extraction
oracle). Regenerate the index. `TODOS.md`: T16-4 closed with the ceiling of
§8; §8 items registered — **keep the literal heading `### T16-4 `**, which
`test_text_commit_cid_hex_tj.py:1562-1580` slices on. `git mv` both plans to
`plans/archive/`.

---

## 5. Cross-slice invariants (pinned once, checked by every slice)

1. Every refusal leaves `doc.tobytes()` identical (pattern of
   `test_text_commit_boundaries.py`).
2. Preview token == commit token for every new `splice_kind`
   (`test_text_commit_candidate_identity.py` pattern).
3. `AppliedPatch.revert` restores the stream byte-identically for every new
   grammar.
4. Across **every** file in `test_scripts/`, a pin is edited only where the
   slice's "pins this slice flips" list names it and its new expected
   outcome; an unexpected red anywhere else is a finding about the slice,
   not a test to fix.
5. `_painter_glyph_ink` never returns a *box* for a shape whose ink it
   cannot bound (`None` is the only honest answer for Type3 and every non-fill
   mode until S3's bound is proven).
6. No `fitz` parameter reaches `replay_page_streams` (D8); `model/` imports
   no Qt and no `scripts/` (`test_layer_boundaries.py`).

---

## 6. Verification per slice

`ruff check .` clean; `.venv\Scripts\python.exe -m mypy model/ utils/` clean;
the slice's new tests red-then-green with the red output pasted into the
plan's log; the text-commit suite (`test_scripts/test_text_commit*.py`,
`test_p4b2*.py`, `test_tier0_target_resolution.py`, `test_glyph_boxes.py`,
`test_text_commit_cid_hex_tj.py`) green, **run one file group at a time,
never concurrently** (CLAUDE.md §Commands; T16-6 hang note); then the census
re-measurement of X2 with the numbers appended to §7.

---

## 7. Log (append as slices land)

| date | slice | plan-survival before → after (fixture) | new dominant code | commits |
|---|---|---|---|---|
| 2026-09-06 | S0 | funnel 0/292 → 0/219 (bind 292→446, undecodable_target 623→0, bind_rate 0.258→0.403 show-weighted on 2-fixture corpus); parity proof: prepare_plan(max_tier=0) cache change improved wall-clock ~2.2x (50.0s → 22.4s) with identical funnel counts; audit (23p, 2237 shows): all refuse not_single_literal_tj (100%); S4 Step 0: run-binding survival 528/1094 = 48.3% (PASS all pivots, top failure shapes: item_contains_partial_word 206, target_not_in_show_text 188, straddles_boundary_with_space_byte 170); S5 Step 0: word-run fragment rate 635/3160 = 20.1% (PASS aggregate, FAIL on the CJK office-report fixture 8.5% alone — S5 defers behind S6 on that fixture); fold 2: page-scope predicate applied to the Tier 1 resource-reuse proof; instruments memoised; ARCHITECTURE + tandem Step 0 pitfalls landed; fold 3 (2026-09-07): census descendant/Differences via production parsers + `items=0` class, audit quote-operator code, funnel palindrome-before-bind and no frame mirror, two stale pitfall references fixed; §8.6 hygiene register | S4 go first (48.3% > 20.1%, both pass pivots; S5 fails on one fixture); bind_rate 0.403, funnel still refuses `not_single_literal_tj` first because S1 not yet landed; S0-b landed, review fold landed (9 findings) | — |
| 2026-09-08 | S1 | office-report-23p (23p, 2237 shows), post-S1: `not_single_literal_tj` is GONE from the audit (0 occurrences, down from 2237/2237 before S1). audit: `tier0_eligible` 0, `tier0_ineligible` 2237; `reject_reason_counts` `mc_wrapper_not_pure_layer` 1959/2237 = 87.6 %, `tj_multi_item_array` 278/2237 = 12.4 %. funnel: `bind_survivors` 180, `plan_attempted` 180, **`plan_survivors` 0**; `plan_fail_reasons` `mc_wrapper_not_pure_layer` 133/180 = 73.9 %, `tj_multi_item_array` 47/180 = 26.1 %. Both instruments rank the same two codes in the same order — S1 alone commits nothing on this fixture, exactly as §1.3 item 1 predicted ("S1 and S2 must land together or be measured together"), and S2 is the next dominant code. **Caveat carried forward, not resolved by this measurement:** the TJ-shape rung runs BEFORE the marked-content rung, so the 278 (audit) / 47 (funnel) `tj_multi_item_array` shows were never evaluated by `admit_show_wrappers` — census shows `mc_depth > 0` on 2237/2237 of this fixture's shows, so MC's TRUE blocking scope is somewhere between 87.6 % (the measured floor) and 100 % (the census ceiling), not pinned to either. CAD-drawing fixture funnel/audit were **not run**: neither instrument has a page-selection flag, so the CAD dependency is demonstrated instead through the Step 12 fixture-pins module (`test_scripts/test_text_commit_s1_fixture_pins.py`), not through these two instruments — do not read "measured on both fixtures" as instrument coverage. Review fold (H1-H3, M1-M2, L1-L4, nine findings) landed on top of the S1 slice itself; see §8.7. | S2 (`mc_wrapper_not_pure_layer`, ≈ 74-88 % depending on instrument) | — |
| 2026-10-23 | S10 | I0d: inline /Annots dictionaries. Red run of the new file: 14 failed, 3 passed (7 x `AttributeError: 'NoneType' object has no attribute 'm_internal'` escaping `prepare`/`commit`/preview render; 7 x ImportError for the not-yet-existing strict reader and typed error; the 3 passes are the C/D/E controls, which commit before and after). Rebuild-action file red on the dto constant alone: generic sentence contained `annotations_not_indirect`. Green after the change: direct_annots 17 passed, rebuild_action 18 passed, decision_chain 6 passed. No change to indirect-annotation pages. Fix round 1 red runs: `Exception: xref 7 is not an annot of this page` (load_annot fallback), `[100.0, 300.0]` instead of `[300.0, 350.0]` (unknown-subtype inline entry); 19 passed. Fix round 2 red runs: `Exception: xref 0 is not a widget of this page` / `xref 7 is not a widget of this page` (stale widget handle), ImportError for `_widget_entries` and `AnnotationListOutOfSync`; direct_annots 26 passed, structural_gates 41 passed. Fix round 3 (refuter MINORs): `require_indirect_annotations` types a raising `annot_xrefs()` as `InlineAnnotationError` (no malformed /Annots shape raises at 1.27.1, so the test monkeypatches); `_widget_entries` walk guarded, `(0, 0, 0, 0)` fallback (a widget /Parent cycle really raises `FzErrorFormat`); red 6 failed (3 detector, 1 prepare, 2 widget-cycle); green: direct_annots 32, structural_gates 41, fingerprint_roundtrip 13. | `annotations_not_indirect` (new, page-shape refusal) | uncommitted |

---

## 8. Ceilings and registered follow-ups

**8.1 Advance-changing edits fall back to legacy at `max_tier=0`.** After
every slice here, a replacement whose advance differs from its source still
refuses `ADVANCE_MISMATCH` at Tier 0 and — with `max_tier=0` — goes to
legacy, where no-jump fidelity is not guaranteed. Tier 1 (transplant + kern compensation + blank-growth
proof) exists and is pinned; enabling it by default is the single largest
remaining jump source and a **rollout decision** with the latency sub-bullet
of TODOS T16-3 criterion 4 (same-session before/after measurement). Register as **T16-7**: measure Tier 1 acceptance and per-edit
latency on the corpus under `TEXT_COMMIT_MAX_TIER=1`, then decide the
default. Likewise `strict` (refuse instead of fall back) — **T16-8**.

**8.2 Paragraph / partial-line targets** (`MULTI_SPAN_TARGET`) need layout
(`layout.py`, deferred since Task 11). Out of scope; the T16-2 cell split
already keeps the *legacy* path from swallowing table rows.

**8.3 Text inside Form XObjects** (`TARGET_IN_FORM_XOBJECT`; 100 % of the
xobject-1p fixture) — the splice primitive works on any stream, but binding,
fingerprint, shared-stream detection and V0a would all need the XObject's
stream as a first-class target with its `/Matrix` and invoking `cm`
composed. Register as **T16-9** with the funnel's `confirmed_in_xobject`
count as its yield metric.

**8.4 Marked content that bears text**: `ActualText`, `Alt` — refused by
design (X4). **Malformed pairing** (595 shows on complex-layout-2p) — refused;
a repair pass is a different kind of change.

**8.5 Zero-corpus glyph classes** (X8): render mode 1 (S8a), `'`/`"`
(S8b — replay records the string operand only and applies `Tw`/`Tc` before
recording, `replay.py:651-690`, so a string-token splice *looks* structurally
safe; **not probed**, and `patch.py:57` / `plan.py:966-981` still refuse both
for whole-op reasons — refused for lack of a fixture and a probe), `rise` (S8c),
`/Differences` + symbolic (S7b), Type0 CFF / Identity-V / non-Identity CMaps
/ unembedded (S9). Each opens on the first corpus fixture that shows it,
with its census number as the acceptance metric. Modes 4–7 (clip) are
**never** admitted.

**8.6 Instrument hygiene register (S0 review fold 3, 2026-09-07).** Verified
by the review finders, not defects, deliberately left for the slice that
touches the code anyway:

- **`tier0_show_gate` extraction (do in S1). Done 2026-09-08.**
  `audit_tier_coverage._classify_show`
  used to hand-mirror the show-level ladder (`plan.py` ~961-1073: operator,
  Tj, text state, wrappers, font, CID-hex); S1 and S7 edit exactly those
  gates. `plan.tier0_show_gate` + `ShowGateAdmission` are now the ONE
  production function `_classify_common` and `scripts/audit_tier_coverage.py`
  both call (imported directly: `from model.text_commit.plan import
  PlanRejection, tier0_show_gate`), so the audit cannot lag a slice that
  moves a gate again (`docs/PITFALLS.md`, "an audit that mirrors a gate goes
  stale the day the gate moves" — amended with this dated sentence). The
  residual TRM exception is likewise now shared through
  `inspect.trm_bind_rejection`, a public, pure predicate `bind_source_text`
  and the audit both call; the glyph-evidence fall-through (a capability's
  own `tier0_reject_reason`, including a font-evidence failure surfacing as
  `unsupported_text_state`) is `tier0_show_gate` ladder step 7, so it moved
  with the rest.
- **Per-(page, resource) capability memo** is copied in `inspect._cid_show_candidates`,
  the audit and the census; hoist into `DocumentFontRegistry` when S6 adds the
  Type3 population walk (a fourth copy otherwise).
- **`page_scoped_font_entries(page)` iterator** next to the predicate, so a raw
  `get_fonts(full=True)` outside `fonts.py` becomes greppable; same S6 moment.
- **Fixture scaffold**: eleven copies of the Helvetica/WinAnsi single-stream
  page builder across five test modules (`test_text_commit_replay_reuse._tier0_doc`
  is the parametrised original); the two scope-collision documents differ
  accidentally. Promote one builder to a shared `test_scripts` module in the
  docs slice.
- **Funnel per-sample cost**: `prepare_plan` per sample re-runs
  `find_pages_sharing_content_stream` (O(pages) C calls), a second stream
  digest and up to three font-program digests per Type0 resource; the fix is a
  keyword pass-through (`frame=`, `resolved=`, `binding=`) on
  `prepare_plan`/`_classify_common`, which is a production API change and its
  own decision (T16-7 latency work is the natural home). The audit's
  `admit_show_wrappers` per show re-resolves `/OCProperties` and the page's
  `/Properties` map; `classify_wrapper` already takes them as kwargs.
- **Funnel over-budget pages**: bind/plan use the default replay budget while
  (b)-(d) use an unbounded replay, so a page production refuses
  `content_stream_too_large` still contributes shows; record the split in
  `methodology` when the first such corpus page appears.
- **`_tj_has_kern_number` returns kernless** when `tj_items` refuses the array
  (name token or malformed hex inside a `TJ`); documented, counted under
  `tj_relex_failed` by the census, not by the funnel.
- **`_resource_font_bindings(entries: object)` + `cast`** should take
  `Sequence[tuple]`; `plan_attempted` is now derived (`== bind_survivors`) so
  the aggregate's independent sum is redundant but harmless.
- **`font_resolution_mismatch`** in the Type0 funnel can no longer fire once the
  predicate filters the population; kept as the single runtime sentinel of the
  `referencer == 0` assumption (measured on PyMuPDF 1.27.1 only), which is
  where a version-independent oracle (compare against the page's effective
  `/Resources/Font` keys) would belong if the pin ever widens.

**8.7 S1 review fold (2026-09-08).** Two independent reviewers checked the
S1 landing against the tandem plan's Fail-closed gates table and D-decisions
and found nine defects, all fixed before this fold closed (the fold was
requested as "eight findings" — nine are independently evidenced by this
session's stage reports, so nine are listed here rather than collapsing two
together or dropping one):

- **H1 — the ExtGState/`w` ordering defeat.** The pen proof read a present
  `/LW` over the recorded `w` regardless of which ran LAST, so `/GS1 gs 5 w
  2 Tr` with `/GS1 <</LW 0.1>>` — measured rendering the 5.0 pen — was
  proved with 0.1, defeating the `STROKE_BOUND_TOO_LARGE` ceiling (the
  gs-less twin refuses at 4.167×) and shrinking the duplicate-gate outset
  from 25 pt to 0.5 pt. Fixed: `_resolve_stroke_pen` replays `ShowOp.pen_
  events` IN ORDER from the initial graphics state; `ShowOp`'s
  `line_width`/`line_join`/`miter_limit` scalars are no longer read by the
  proof.
- **H2 — an undefined join or sub-minimum miter limit was floored into an
  admission.** `_prove_stroke_pen` now refuses `line_join ∉ {0, 1, 2}` and
  `miter_limit < 1` BEFORE the ceiling; `_stroke_outset_visual`'s
  conservative factor floor moved from `max(M, 0.5)` to `max(M, 1.0)` and
  its miter test from `line_join == 0` to `line_join not in {1, 2}` (a
  negative join renders MITER in MuPDF; "not 0 ⇒ no miter" had collapsed
  the bound 10×).
- **H3 — a malformed pen operand read as "unchanged."** A malformed
  `w`/`j`/`M`/`gs` operand now refuses `STROKE_BOUND_UNPROVEN` naming the
  operator, from the `(op, None)` event replay records, rather than a
  scalar sentinel a later `gs` could silently overwrite.
- **M1 — `page_fingerprint` did not cover the ExtGState table the pen proof
  reads.** Rewriting an ExtGState's `/LW` from a provable value to an
  unprovable one left the fingerprint byte-identical, and a cached
  `PreparedEdit` committed against a stroke bound the page no longer
  justified (measured: it came back `COMMITTED`). Fixed:
  `_update_extgstate_dependencies` folds the page's effective
  `/Resources /ExtGState` table, folded LAST so a page with none
  fingerprints exactly as before.
- **M2 — the duplicate gate's twin-side outset was missing.** Step 9 grew
  only the TARGET's core by its proven pen and left every non-fill twin on
  its bare advance core, so a same-bytes twin painting `2 Tr 5 w 10 M` was
  called disjoint 0.1 pt clear of a fill-mode target while its rendered
  stroke ink reached 0.208 pt into that target's core. Fixed:
  `_twin_stroke_outset` grows every candidate whose `render_mode != 0` by
  its OWN conservative bound, resolved the same way the target's is. Its
  own ordering defect (an unboundable twin refusing unconditionally, ahead
  of the un-outset comparison, silently overwriting existing p4b2 verdicts
  for modes 1 and 7) was fixed separately: the outset only ever grows a
  core, so it is monotone on the overlap predicate, and the fix refuses on
  the un-outset comparison first, changing which SENTENCE a refusal
  carries, never which pages are admitted.
- **L1 — a Tier 1 transplant carried the wrong splice-kind label.**
  `_build_tier1` left `PreparedEdit.splice_kind` on its `"string_token"`
  default even though it replaces the WHOLE show operator; only the `is
  TIER0_...` check ahead of the dispatch kept the wrong verification arm
  from running. Fixed: `_build_tier1` sets `SPLICE_KIND_WHOLE_OPERATOR`,
  and `_target_operator_failure` checks the label before trusting the tier.
- **L2 — (verified, not a new defect this fold).** The three TJ inner-item
  cells (commit touches only the inner span, preview token == commit
  token, `AppliedPatch.revert` byte-identical) were checked directly
  against the landed code rather than assumed from the plan text.
- **L3 — instruments double-counted a shape the production gate had
  stopped refusing.** `_sole_loss_class` booked a show as `tj_array_only`
  even once the production gate admitted its operand, so the Type0
  vocabulary counterfactual counted four shows twice (once in the
  baseline, once in the counterfactual asking what admitting them would
  buy) and the glyph-overlap census mislabeled three re-shaped fixtures.
  Fixed: `_sole_loss_class` books `tj_array_only` only when the production
  gate still refuses the operand; `test_type0_vocabulary_counterfactual.py`
  and `test_glyph_overlap_census.py` re-pinned to the corrected counts
  (§4 S1 "Pins this slice flips" extension above).
- **L4 — the fixture-pins module overstated its own privacy contract.**
  "Never by name" read as stronger than the code actually does: the
  fixture is located by a glob on a FRAGMENT of its file name, per the
  repo's `needs_fixtures` convention. Fixed: the module's own docstring
  narrows the claim to what it actually guarantees (role-only prose,
  fragment-glob location), not a claim the fragment itself is absent.

**Residual, not a defect (recorded so the next reader does not re-derive
it):** the twin-side outset (M2) covers only a mode-2 twin with a pen
`_resolve_stroke_pen` can replay. Every other non-fill twin — mode 1, mode
3 (until S7), modes 4-7, or a mode-2 twin whose pen cannot be resolved
(an unreadable ExtGState, a malformed operand) — has NO bound at all and
is refused outright with the existing "cannot prove target placement"
string. This is deliberately asymmetric with the target side, which
Phase B (S3) still owes a stroke ink bound for inside `_painter_glyph_ink`
itself (`plan.py:517`'s `continue → return None` and the admission of mode
2 into the exact arm) — until then, a mode-2 TARGET with a same-bytes twin
stays refused, which is the correct fail-closed outcome, not a gap this
fold could close.

**F6 closure 2026-09-20 (Astra medium peer):** an independent verifier
rechecked H1-H3, M1-M2, and L1-L4 against the landed code and targeted
tests. The protected p4b2 pins remained unchanged; the targeted S1/review
set passed **391 tests**, `ruff check .` passed, and
`.venv\Scripts\python.exe -m mypy model/ utils/` passed for 53 files.
No files were changed by the verifier. The full suite remains intentionally
unclaimed: its separate Qt printing run exited non-zero with Windows
`0x80040155` diagnostics, so it is not a release gate for this closure.

---

## 9. Execution

Follow `CLAUDE.md` and the current user request. The former model-specific
Workflow orchestration has been removed; it added no PDF correctness proof.
Implement only the next evidence-backed slice, then measure its effect.
Commit only when requested.

## 10. Open questions

1. S2: is `Lang` the only structural key beside `MCID` that Office emits on
   `/P`/`/Span`? Measure the key sets on the three Office fixtures before
   fixing the inert set (fail-closed either way).
2. S4: does MuPDF synthesise a space for a kern of exactly 0.2 em, or is the
   threshold size-dependent? The token-wise rule does not depend on it (it
   uses the *target's* spaces), but the funnel's dict-line targets do.
3. S5: `Tw` on Identity-H shows — 2-byte codes never receive `Tw`
   (`glyph_boxes.py:274`); confirm the fragment advance helper shares that
   rule with `predict_glyphs` by test.
4. S6: resolved by P-E — the `.00048828127` (`1/2048`) font fails the
   integrality rule on 2024/2048 widths and is refused `TYPE3_WIDTH_UNPROVABLE`
   unless the quantised advance is adopted per code; decide in S6 Step 0 by
   counting how many of its shows the corpus actually contains.
5. Resolved: the CAD census (476 kerned arrays vs 9 `2 Tr` shows) and the
   critic's ordering verdict put S3 last among the engine slices.
6. StructElem-level `/ActualText`/`/Alt` via `/StructParents → /ParentTree`
   (X4): unmeasured; S2 Step 0.
7. Mode-3 extraction (S7 Step 0 probe P-G): unmeasured.
8. The probe scripts behind §1.2 live in this session's scratchpad until S0
   promotes them; until then no number in §1.2 is reproducible by the next
   reader — that is why S0 is first.
