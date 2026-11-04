# Claude Code：真文字高保真提交

## Owner and hand-off contract

**Executor: Claude Code.** The companion gpt-5.6-sol test plan,
`plans/archive/2026-09-22-real-corpus-type0-acceptance-tests.md`, owns the acceptance
tests and must be completed first. Start by reading and running those tests; do
not change an assertion, lower a visual/resource threshold, replace the
real-fixture check with a skip, or implement vector / outlined-letter editing.

This plan is intentionally limited to genuine PDF text. The in-scope real-fixture
acceptance corpus is the HVAC document's ten Type0 edits plus [ECC_DWG]'s four
`DFKaiShu-SB-Estd-BF` Type0 edits. The CHB and Taoyuan vector cases are deferred in
`TODOS.md` and must not be added as an implicit fallback or claimed as success.

## Required outcome

For every corpus edit, a normal run-level edit in the application must use the
original embedded Type0 font resource and source CID mapping. It must preserve the
actual PDF text state (`Tf`, `Tm`, CTM, `Tz`, `Tc`, `Tw`, rise and render mode),
commit the exact previewed patch set, reopen correctly, and retain zero rendered
change outside the target union. A changed advance must preserve the following
text origin through a `TJ` adjustment; a same-advance replacement must change only
the hex string operand.

When the proof cannot establish this outcome, keep the user's editor input and
report a refusal. Legacy redact/reinsert is available only through a distinct,
user-selected rebuild action with its existing disclosure; it is never an automatic
fallback for a normal edit.

## Scope fences

Do:

- Preserve source CID text by using `DocumentFontRegistry`, strict CID encoding,
  glyph coverage gates and `StreamReplacement` / `splice_stream`.
- Extend only the admission and user-flow gaps evidenced by the fourteen real
  Type0 cases.
- Keep the MVC boundary: View signals to Controller; Controller invokes Model;
  Model remains Qt-free. Use QThread / signals for preview work.

Do not:

- Insert a system font, add a font program, invoke HTML/CSS preview as a fidelity
  substitute, rasterize text, or infer fonts from vector paths.
- Implement outlined / vector letters, missing glyph embedding, multi-run or
  paragraph replacement, Form XObject editing, arbitrary shear/rotation support,
  or automatic legacy downgrade.
- Reformat untouched streams, weaken stale checks, bypass resource guards, or
  change user-provided experimental source files.

## Implementation sequence

### 1. Make scratch-page identity semantic without weakening stale protection

`model/text_commit/inspect.py` currently lets a scratch serialisation turn
numeric ExtGState values such as `1.0` into `1`. The fingerprint then differs by
PDF lexical spelling, not rendering meaning, and rejects valid plans before a
commit.

Canonicalise scalar numeric PDF values in both `_canonical_object_digest()` and
the scalar branch of `_fold_canonical_value()` using the existing PDF-value parser
and a single exact numeric formatter. `1`, `1.0` and `1.000` must fold alike;
different numeric values must remain different. Preserve strings, names,
booleans, nulls, references, arrays and dictionaries as their current semantic
classes. Do not introduce a rounding tolerance.

Keep `page_fingerprint()` covering decoded streams, complete Type0 evidence,
marked-content dependencies, page geometry, annotations/widgets and ExtGState.
Add a counterfactual test that changes a real ExtGState opacity/line setting and
still makes the prepared edit stale.

### 2. Correct marked-content handling for valid graphics save/restore nesting

In `replay.py`, `crossed_q` currently makes a BDC/EMC wrapper malformed merely
because its graphics-state save depth later crosses a `Q`. The HVAC runs prove
that this is not a sufficient reason to refuse otherwise paired visible content.

Track marked-content scope and graphics-state scope independently. Preserve all
real integrity gates: BMC/BDC/EMC underflow and pairing, stream ordering, target
range containment, hidden content, non-default OCG visibility and malformed
operators must still refuse. Reclassify the verified valid wrappers as usable;
do not globally ignore q/Q or reorder operators.

### 3. Admit only the demonstrated mirrored text shape

`transforms.shape_reject_reason()` rejects every reflected TRM. Add a narrow
positive path for the HVAC mirrored Type0 run: finite, non-singular, orthogonal,
uniform-scale, cardinal-baseline, fill-mode source text whose replacement is
admitted by the existing CID and advance proof. Continue mapping all four text
quad corners through Tm, CTM and the visual page frame.

Retain refusal for non-uniform transforms, shear, arbitrary angles, singular
matrices, strokes, hidden/clip-dependent rendering and reflected edits whose
advance/growth proof is not established. The goal is the recorded case, not a
blanket det<0 acceptance.

### 4. Reuse the Tier 0/1 splice paths and make their defaults reachable

Use the existing Tier 0 hex-operand splice for equal advance and Tier 1 whole
`Tj` → `[<new-cids> K] TJ` replacement for unequal advance. K remains:

`(new_advance - old_advance) * 1000 / Tf`

Do not alter source `Tf`, `Tm`, CTM, `Tz`, spacing, rise or font resource.
Keep glyph coverage, source-encoding round-trip, overlap, shared-stream and
growth checks. The ECC `[ECC_DWG] → ECC-3` case is the concrete unequal-advance
acceptance; the existing excluded TJ forms stay refused unless a test proves they
preserve their original kern semantics.

Set shipped `TextCommitSettings` to the successful route: `engine="tiered"`,
`max_tier=1`, and `preview="plan"`. Keep diagnostics behind their existing
environment settings. A configured `legacy` kill switch remains possible for
operators, but it must not be selected by ordinary failure handling.

### 5. Make preview, commit and edit-result truth the same operation

The plan preview must prepare on the same snapshot and render the same patch set
that normal Apply commits. In `controller/text_commit_coordinator.py` and
`view/text_editing.py`, use the existing generation and token gates: only a current
verified preview can be applied, while a pending/stale request shows the original
or last verified PDF frame and retains typed input. With `preview="plan"`, do not
show a CSS or system-font interim preview that claims font fidelity.

Default target selection to a single run, retaining its source span ID and
coordinates to distinguish twins. Do not turn run edits into paragraph edits.
Only explicit user changes to style controls may populate `StyleOverrides`; an
extracted display size is evidence, not permission to restyle the source.

Add `allow_rebuild: bool = False` to `EditTextRequest`. The ordinary Apply flow
passes `False`; model code treats absent consent as refusal, never permission to
call legacy insertion. Add a separate UI action labelled as rebuilding text. It
sets `allow_rebuild=True`, invokes the existing degrade confirmation, and scopes
approval to the current target and text. Any refusal, stale token, preview failure
or declined rebuild must keep the editor open with its input. Finalisation must
use the real `CommitOutcome`, never equate a signal delivery with `COMMITTED`.

### 6. Preserve undo, redo and save semantics

High-fidelity commits must record forward/inverse patch sets in
`EditTextCommand`; undo/redo replays those exact patch sets rather than calling
legacy insertion. Keep fidelity-protected pages from content cleanup. Do not force
incremental save as a product policy: retain existing encryption, Save As and
atomic-full-save paths. After a full save may renumber xrefs, invalidate prepared
preview/cache evidence rather than asserting xref numbers stay fixed.

## Verification and completion

Run the gpt-5.6-sol acceptance tests first and retain their red failure before
implementation. Completion requires all of the following:

1. All 14 real Type0 cases commit as high-fidelity commits through the normal UI
   path; none reports `DEGRADED_COMMITTED`, selects a system font, or takes the
   legacy branch.
2. CID text/resources, state/origin invariants and decoder/reopen assertions pass.
   For each page, 6x target crops differ and 2x or higher non-target pixels are
   exactly zero in MuPDF and Poppler.
3. Positive and negative unit coverage exists for numeric canonicalisation,
   meaningful stale changes, valid q/Q marked content, malformed/hidden content,
   narrow reflection admission, missing glyphs, stale preview tokens, explicit
   rebuild approval and declined rebuild zero-mutation behavior.
4. QTest exercises target selection, type → debounce → preview → Apply, rapid
   input supersession, undo, redo and save/reopen for the real text corpus.
5. Run `.venv\\Scripts\\python.exe -m pytest` for relevant changed suites, then
   one complete suite; `.venv\\Scripts\\python.exe -m mypy model/ utils/`; and
   `ruff check .`. Render the final real PDFs in the application before hand-off.
6. Update `docs/ARCHITECTURE.md` for public flow/data changes, add a focused
   `docs/PITFALLS.md` entry plus regenerated index, update `TODOS.md`, and archive
   this plan only after the scope is actually complete. Do not commit or push
   unless the user asks.

## Expected initial failures

Before implementation, the real corpus records four blocker families:

- `verification_failed` from scratch fingerprint numeric spelling;
- `mc_malformed_pairing` on valid marked content that crosses graphics saves;
- `trm_reflected` on the demonstrated mirrored HVAC Type0 case;
- default Tier 0/legacy/UI behaviour that can preview or commit a non-identical
  path instead of the verified Tier 0/1 patch.

If a test reveals a different blocker, investigate it and extend only this
true-text plan with its evidence. Do not use a vector experiment to work around it.
