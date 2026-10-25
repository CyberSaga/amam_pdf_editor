# V12 triage memo: batch 20261024_2116_r2, the 28 quarantined rows

Date: 2026-10-25. Scope: the 28 `quarantined` outcomes of the first full
frontier run (brief_revision 3). Inputs: validator report, rederive report,
three investigator reports (granularity, locate-and-canary,
provenance-and-order), two refuter reports. Every contested claim below was
re-checked against the files at HEAD e0e80c2 plus the uncommitted V11 tree;
line numbers are from that tree and will drift once V11 is committed.

Loop rule applied: run first, prune the contract from what actually failed.
Fixes to OUR contract (brief, validator, rederive) are V-numbered and tested
red-first; Grok record defects go into the next brief paste as explicit rules.

Legend for the classification column:

- `ours: contract ambiguity` -- the brief is silent or conflicts with itself;
  Grok and rederive each picked a defensible reading.
- `ours: rederive gap` -- the brief (or the design doc) is clear and rederive
  does not follow it, or reports its own failure as a product fact.
- `ours: validator gap` -- a rule the brief promises that the validator does
  not enforce.
- `grok: record defect` -- the record departs from a rule the brief states
  clearly.
- `expected: provenance pending I0a` -- by design until owner decision 7 /
  I0a registers the files.
- `product: nondeterminism?` -- not used; nothing in the 28 rows is one.

Where a row has two independent causes both are listed; the first is the one
that decides which fix clears it.

## 1. The 28 rows

| # | case_id | quarantine codes | divergent fields | classification | one-line reason |
|---|---------|------------------|------------------|----------------|-----------------|
| 1 | r2-F2I-f17a0919-p0-s0-eq1 | remeasure | original, original_sha256, target_bbox_raw | ours: contract ambiguity | Brief M0/M1 (L308-322) decode and locate the WHOLE show; section 3.3 L237 makes the target ONE item. Grok wrote the item, rederive measured the show (evidence_rederive.py:558, :1165-1169, :1178-1186). |
| 2 | r2-F2I-bdb495e9-p0-s5-eq1 | remeasure | same as #1 | ours: contract ambiguity | Same as #1. |
| 3 | r2-F2I-f723638d-p0-s0-eq1 | remeasure | same as #1 | ours: contract ambiguity | Same as #1; verified on the public file: record bbox = the `Lorem` glyphs, recomputed bbox = the whole 15-item show. |
| 4 | r2-F2R-f17a0919-p0-s4-eq1 | remeasure | original, original_sha256, target_bbox_raw | ours: contract ambiguity | Same mechanism for a tj_run (L238). Grok's K_sum / internal_kerns_dropped / byte spans re-derive on the file. |
| 5 | r2-F2R-f723638d-p0-s1-eq1 | remeasure | same as #4 | ours: contract ambiguity | Same as #4. |
| 6 | r2-F2R-bdb495e9-p0-s2-eq1 | remeasure | same as #4 + verify_bbox_visual | ours: contract ambiguity | Same as #4; verify_bbox cascades from the whole-show advance. |
| 7 | r2-F2G-f17a0919-p0-s4-grow1 | remeasure | expected_origin_visual, original, original_sha256, target_bbox_raw, verify_bbox_visual | ours: contract ambiguity | Non-leading run: whole-show locate puts expected_origin at the show origin, Grok put it at the run's first glyph (section 3.3 L243 reading). |
| 8 | r2-F2G-f723638d-p0-s0-grow1 | remeasure | same as #7 | ours: contract ambiguity | Same as #7; verified: run `eirmod` at x 472.94 vs show origin x 100.2. |
| 9 | r2-F3-db5c34fe-p0-s0-eq1 | remeasure | adv_new/adv_old_text_space, expected_origin_visual, fragment_ranges, original, original_sha256, target_bbox_raw | ours: contract ambiguity | `target.item_range` is never defined in the brief (schema only, L429). Grok wrote an item INDEX pair; rederive reads stream BYTE offsets (:1095-1107) and then slices the stream with it (:1320-1335), producing the advance cascade. |
| 10 | r2-F3-f723638d-p0-s7-eq1 | remeasure | adv_old_text_space, displacement_ink, expected_origin_visual, fragment_item_range, original, original_sha256, target_bbox_raw, verify_bbox_visual | ours: contract ambiguity | Same as #9 (fragment_item_range: record [0,1] vs recomputed [1377,1384]); one root cause, five cascaded fields. |
| 11 | r2-F3-bdb495e9-p0-s49-eq1 | remeasure | same as #10 | ours: contract ambiguity | Same as #10. |
| 12 | r2-F3-bdb495e9-p0-s49-neg1 | remeasure | detail, expected_origin_visual, original, original_sha256, prepared, reason, result, target_bbox_raw, tier | ours: rederive gap (+ #9 ambiguity) | rederive probes with target_text = whole show and replacement = the fragment replacement (frame_prepare :1497-1498) and actually PREPARED that mixed edit at Tier 1; section 3.4 L262/L265 define the probe on the fragment and predict no_source_match, which Grok recorded. |
| 13 | r2-CANARY_TC-9da93de9-p4-s11-can1 | remeasure | adv_old_text_space, displacement_ink, verify_bbox_visual | ours: rederive gap | Canary rows are exempt from the one-change rule (L625); rederive reads changes[0] as the string operand (:1305-1349) but changes[0] is the zero-width `Tc` insertion, so adv_old = 0.0. Grok's advance object is exactly what L120 prescribes. |
| 14 | r2-CANARY_FONT-9da93de9-p4-s11-can1 | remeasure | adv_old_text_space, after_bbox_raw, displacement_ink, verify_bbox_visual | ours: rederive gap | Same changes[0] defect as #13 plus the after-locate: rederive searches the after texttrace by replacement TEXT with no distance gate (:2049-2062) and lands on a pre-existing second occurrence of the replacement string 76.56 pt away (hash-verified on a copy). Grok's after box is 6.1 pt wider, which L120 predicts. |
| 15 | r2-CANARY_WRONGGLYPH-9da93de9-p4-s11-can1 | remeasure | after_bbox_raw | ours: rederive gap | Only the after-locate defect of #14 (single change, so no advance cascade). Confirms the diagnosis of #13/#14. |
| 16 | r2-F17-1017c455-p0-s1-cen1 | remeasure | exception_type, font_kind, locate, reason, result | ours: rederive gap (+ contract gap) | (a) rederive scores its own LocateError as a product `exception` and compares it with the recorded `rejected/untracked_advance` (:1504-1506, :1531-1555): 9 of the 10 divergences are that one failure. (b) font_kind: rederive derives it from `cap.cid` (:1155), Grok from /Subtype; the brief does not say which (L418 enum only, L627 ties type0 to the CID advance function). (c) The recorded target geometry describes show 0's glyph, not this show: M1 L320 anchors on `show.origin_user` with no exception for origin_reliable=false and L331 forbids retrying, so this is a contract gap Grok disclosed in limits (record line 361), but the numbers are wrong and must not pass. |
| 17 | r2-F30B-644ac66a-p0-s0-eq1 | provenance_unverified, remeasure | exception_type, locate, reason, result | expected: provenance pending I0a (+ rederive gap of #16a) | Wingdings TrueType with no ToUnicode: texttrace unicode is U+FFFD, so the text-match locate (M1 L319) cannot succeed; Grok located positionally (disclosed). Product verdict `encoding_failed` is correct and reachable without locate. sha 644ac66a is not in public_corpus_sha256.json; the file is intact and hash-verified on disk. |
| 18 | r2-F5-69f6b7f4-p0-s830-cen1 | remeasure | exception_type, locate, reason, result | ours: rederive gap (#16a) + contract gap (M1 has no positional branch) | Type3 glyph whose texttrace unicode is a PUA code point; same as #17 without the provenance leg. Grok's positional geometry equals the glyph box at distance 0. |
| 19 | r2-F2I-f17a0919-p0-s0-neg1 | reason_order | (none) | ours: rederive gap | Static predicate at :1753-1754 fires on every F2I/F2R row with expected_reason tj_multi_item_array, before any measurement. This row is the whole-show negative twin that brief L237 ORDERS; record and recompute agree on both tiers. The predicate implements design.md:117/:228 (R3-1) verbatim, so the design doc conflicts with the brief. |
| 20 | r2-F2R-f723638d-p0-s1-neg1 | reason_order | (none) | ours: rederive gap | Same as #19. |
| 21 | r2-F30W-600d25fc-p0-s0-eq1 | provenance_unverified | (none) | expected: provenance pending I0a | isartor-6-3-2-t01-fail-a, not in the sha table; file intact, divergences empty, probe `encoding_failed` reproduced. Brief L151 says exactly this happens. |
| 22 | r2-F30W-600d25fc-p0-s0-neg1 | provenance_unverified | (none) | expected: provenance pending I0a | Same file as #21. |
| 23 | r2-F30W-b19edaa3-p0-s0-eq1 | provenance_unverified | (none) | expected: provenance pending I0a + grok: record defect (slug) | veraPDF 6-8-3-3-t01-fail-a, not in the sha table; reached save_reopen_pass with no divergences. Slug `vera-6-8-3-3-t01-fail-a` violates L374 (`_slugify(stem)` gives `verapdf-test-suite-6-8-3-3-t01-fail-a`); the validator has no slug-derivation check (ours: validator gap). |
| 24 | r2-F30N-6c37fb06-p0-s0-eq1 | provenance_unverified | (none) | expected: provenance pending I0a | isartor-6-3-4-t01-fail-d, not in the sha table; same lineage as the registered -g variant, so it adds no second lineage. |
| 25 | r2-F1-00640a01-p0-s0-neg1 | provenance_unverified, before_pdf_mismatch | (none) | ours: contract ambiguity + expected: provenance pending I0a | `relative_path=null` on a local_unrecorded row. Section 5.4 L754 groups local_unrecorded with proprietary under "always" and lists relative_path among the redaction fields; only L755 narrows the null to proprietary; L152/L269 claim the file is already in the manifest; the manifest does not exist at HEAD (L226 admits it). Nothing mismatched: bundle before.pdf sha == source sha, file on disk hashes to 00640a01. `before_pdf_mismatch` here means "unresolvable" (:891, :898). |
| 26 | r2-F1-faefb744-p0-s30-neg1 | provenance_unverified, before_pdf_mismatch | (none) | ours: contract ambiguity + expected: provenance pending I0a | Same as #25, file test-complexed-layout (faefb744, intact on disk). |
| 27 | r2-F5-faefb744-p0-s0-cen1 | provenance_unverified, before_pdf_mismatch | (none) | ours: contract ambiguity + expected: provenance pending I0a | Same as #26. |
| 28 | r2-F17-faefb744-p0-s28-cen1 | provenance_unverified, before_pdf_mismatch | (none) | ours: contract ambiguity + expected: provenance pending I0a | Same as #26. An F17 row: once resolved it will carry the same untracked-origin geometry question as #16c. |

Tally by primary classification: ours contract ambiguity 11 (#1-11) + 4
(#25-28, shared with provenance) = 15; ours rederive gap 8 (#12-16, #18-20);
expected provenance pending I0a 5 primary (#17, #21-24) + 4 secondary; grok
record defect 1 secondary (#23 slug); product nondeterminism 0.

## 2. Where investigators and refuters disagree, and the pick

1. Group A `target_bbox_raw` / `expected_origin_visual`. Granularity
   investigator: rederive modelling gap, M1 incoherent. Refuter 1: the brief
   conflicts with itself; M0 L308-310 decodes `show.decoded_bytes` (the whole
   show), M1 L319 "match the decoded text" refers to that decode, L321
   `chars[0]` is the show's first glyph, and the neighbours pairing rule L702
   anchors `[i, i+n_old)` on the show's first glyph too; rederive implements
   that literally. Verified: all four lines read as refuter 1 says. Pick:
   refuter 1. It is a contract self-conflict (M0/M1/L702 say show, sections
   3.3/3.4 and the validator's target-run sizing at evidence_bundle.py:1992-
   2004 say slice). Consequence: brief v4 must restate M0, M1 and L702 for
   sub-show targets, not just M1; rederive then follows. "No Grok misrecord"
   is kept, with the amendment that Grok departed from the literal M0/M1 and
   wrote the slice into `source_decode.latin1` (against L310).

2. Group B `item_range`. All parties agree it is undefined. Pick index
   semantics (half-open item indices into the TJ array), because
   `array_item_count` sits beside it (L428), section 3.3 speaks of "one item /
   item run", and a byte-offset `item_range` would duplicate
   `changes[0].start/end_old` on every TJ row. Refuter 2's amendment A5 is
   adopted: the rewritten rederive test must keep its failure cases
   (index into another show's array, i1 > array_item_count, i0 >= i1, F3 with
   i1 != i0+1, lexed span of items [i0,i1) != changes[0] span). Which
   brief_revision the new reading applies to is an owner question (Q1).

3. Group C habibi geometry. Locate investigator: Grok misrecord. Refuter 1:
   contract gap (M1 L320 has no origin_reliable exception, L331 forbids a
   retry, Grok disclosed the mismatch in limits, and the geometry fields are
   non-nullable in brief L439/L568-570 and schema line 61, so the proposed
   "MUST be null" rule cannot ship alone). Verified. Pick: contract gap for
   the label, but refuter 2's A7 for the effect: the recorded numbers describe
   the wrong show and rederive must flag them (`geometry_on_untracked_origin`)
   rather than close them as unverifiable. Nullable geometry needs the schema
   change first (V13 below).

4. Group C `font_kind`. Investigator: record right, rederive wrong.
   Refuter 1: ambiguity (L159 is about unmappable replacements, not font
   type; `font_subtype` is a separate field L432; L627 ties font_kind=type0
   to the CID advance function, which needs `cap.cid`; rederive's own rule
   :1155 is mixed). Verified. Pick: ambiguity, resolved toward /Subtype in
   brief v4, because the L627 advance rules are about CID arithmetic and
   /W widths, which a codec-less Type0 still has; a 2-byte CID font labelled
   `simple` would make the simple-font advance rules apply to it. Brief v4
   must then name the advance_function for a codec-less Type0 (census only,
   mutation forbidden, `advance_unprovable`).

5. Group C LocateError. Both refuters accept C-2 (do not score a LocateError
   as a product exception). Refuter 2 tightens it: own quarantine code
   `target_unlocatable`; the reason-only fallback probe
   (`expected_origin=None, target_bbox=None`) is gated on kind in
   {census, negative}, not on `mutation is None` (F30B-644ac66a is a positive
   with a null mutation, record lines 8 and 184); the fallback requires
   exactly one replayed show decoding to the target bytes and it must be the
   record's show_seq; a record with non-null geometry that rederive cannot
   locate stays quarantined. Pick: refuter 2's version.

6. Group C positional locate (C-3). Refuter 1: a contract change to M1, not a
   rederive-only fix. Refuter 2: allowed only when the texttrace glyphs at
   the anchor are undecodable (U+FFFD / PUA), origin_reliable is True from
   the replay, one contiguous span, n from rederive's own decode, and the
   method is recorded. Pick: both. Brief v4 M1 gains an explicit positional
   branch with those preconditions; rederive implements it as a pure
   fallback so the control bundles never take it.

7. Group D canaries. Investigator D-1/D-2 accepted with refuter 2's A9/A10:
   the operand selector requires exactly one STRING/HEXSTRING change inside
   [op_start, op_end) and zero-width operator-only insertions for the rest
   (anything else is `canary_changes_shape`), limited to the
   experiment/canary path so `_check_prepared` and the controls are
   untouched; the after-locate anchors on the before-origin rederive located
   (never on the record's after_bbox_raw, which :2054-2056 does today for
   sub-show rows) with the 0.02 pt gate, and the after-text identity check
   stays as a separate observation because rederive has no other
   glyph-identity or extraction check until I1. Investigator's policy
   finding stands: canaries are replayed by design (:1683-1685, :1696; only
   CANARY_UNSAVED is skipped); a remeasure quarantine on one is a modelling
   gap, not policy.

8. Group E `reason_order`. Provenance investigator: over-broad predicate.
   Refuter 1: the predicate implements design.md:117/:228/:392 verbatim, so
   the design doc must be amended with it. Refuter 2: the exemption must be
   decided from recomputed facts (sha256(scene.text) == original_sha256,
   mutation null, kind negative, byte_range null), never from the record's
   `item_range` alone. Pick: all three. Not product nondeterminism, not a
   Grok defect: record and recompute agree on both tiers.

9. Group F `relative_path=null`. Investigator: Grok misrecord the contract
   fails to catch. Refuter 1: contract ambiguity (L754 grouping, L35/L375
   promise sha-based resolution, L152/L269 say the files are registered,
   Grok's limits line 376 state this reading). Verified. Pick: contract
   ambiguity; the fix is a NEW rule (`relative_path_required`), pasted as
   "the contract now says", not "Grok deviated". The b19edaa3 slug remains a
   clear Grok defect against L374.

10. Owner decision 2 (X5). Refuter 2 A12: clearing the F2R/F2G remeasure
    quarantines makes those rows emit-eligible once I0b lands
    (DEFAULT_PLANNED :91 includes F2R/F2G with no owner; emit_rows :2258-2268
    would write candidate rows), and the F2R negative twin becomes
    engine_active after the reason_order fix. Pick: an explicit
    measurement-only hold must land in the same change set (owner Q2). Also
    corrected: the eq/grow rows are experiments (record `path: experiment`),
    so after the fix they land as `deferred` (oracles_incomplete,
    :1648-1663, :1787-1792), not `rederived`.

11. Control bundles. Refuter 2 A13: `slug_not_derived` must be gated on
    brief_revision >= 3 because 1114 (rev 2, local_unrecorded, slug `hvac`,
    relative_path `test_files/hvac-dwg.pdf`) would gain a violation.
    Verified on the 1114 records. Pick: gate both new validator rules on
    rev >= 3; acceptance criterion for every V-fix is byte-identical
    validate and rederive reports for 1114 and 1713.

## 3. V12 scope proposal

The triage package is one umbrella (V12) with five numbered parts so the loop
plan log can land them in separate commits; the parts are V12 to V16 to
avoid the V-number collision both refuters flagged. Every part: red-first
test, ruff clean, 1114 and 1713 reports byte-identical, docs/PITFALLS entry
plus index regen, docs/ARCHITECTURE.md quarantine vocabulary updated.

### V12 -- target granularity (rows #1-12)

Ours, brief v4 text (pasted to Grok as "the contract now says"):

- Section 5.1 `corpus_case.original`: the decoded TARGET text (whole show
  for string_token / whole_operator / product_commit; the item for tj_item;
  the run concatenation for tj_run; the decoded [b0,b1) slice for
  string_fragment / fragment_split). `original_sha256` = sha256(UTF-8) of
  that string. New field `corpus_case.show_text_sha256` = sha256 of the whole
  decoded show, required on every row, so show identity stays checkable on
  non-public rows.
- Section 5.1 `target.item_range`: half-open INDEX range of string items in
  the TJ array, 0 <= i0 < i1 <= array_item_count; null for Tj/'/" and for
  whole-array targets; F3 requires i1 == i0+1 and `byte_range_in_item` is
  decoded byte offsets inside item i0.
- Section 4 M0/M1 and section 5.2 L702, restated for sub-show targets:
  (i) locate the whole-show run by `show.origin_user * frame.base`
  (< 0.02 pt, unchanged); (ii) the target char sub-range inside that run is
  [c0, c0+len(original)) where c0 = decoded length of items before i0 plus
  b0; `expected_origin_visual` = that sub-range's chars[0] origin,
  `target_bbox_raw` = union of its bboxes; neighbours pairing anchors on
  i + c0, not i. `source_decode.latin1` stays the whole-show decode (M0
  L310); the slice is `original`.
- Section 4 M1 probe: `target_text` = `original` (the slice); the recorded
  reason is the slice probe. Record the whole-show probe as a second view
  `probe.whole_show_max_tier_1` for the tj_multi_item_array evidence.

Ours, rederive:

- Derive the target text from the PDF, never from the record: lex the
  string items of `stream[op_start:op_end]`, decode items [i0,i1) (or item
  i0 sliced to [b0,b1)), compare `original_sha256` and `original` against
  that derived text (refuter 2 A1). `_check_changes` additionally checks that
  the decoded payloads of `stream[start:end_old]` (kerns excluded) equal the
  derived target, and for F3 that the old token is exactly item i0's lexed
  span (A2).
- Locate: char sub-range recipe above on top of the existing whole-show
  locate; require the sub-range's texttrace unicode == derived slice when
  the font decodes (A3; guards ToUnicode multi-char mappings and the
  "substring occurs twice" negative L267).
- Probe: `frame_prepare` passes the derived slice as `target_text` with the
  sub-range geometry; keep a coherent whole-show probe (target = scene.text,
  replacement = prefix + slice replacement + suffix) as the second view
  (A4). Recompute `no_source_match_subclass` from the derived target and
  compare it (today nothing reads it: schema line 64 only).
- `item_range` index reading replaces :1095-1107 and :1320-1335; the
  `whole_show` flag at :2054 is unchanged in meaning.
- Tests (red first): invented `original` of the same length diverges;
  `original` naming a different item than `item_range` diverges; each A5
  index failure case diverges; the F3 "substring twice in one item" negative;
  rewrite test_evidence_rederive.py:2461-2490 to index semantics;
  F3-bdb495e9 s49 neg1 shape recomputes `no_source_match`.

Ours, validator: `item_range_bounds` (0 <= i0 < i1 <= array_item_count; F3
i1 == i0+1), `item_range_span` (lexed byte span of items [i0,i1) plus
internal kerns for tj_run == changes[0].start/end_old),
`show_text_sha256_required`. Gated on brief_revision >= 4 (the field is new
to v4); the index-bounds check can additionally run on rev 3 because no rev-3
record carries byte offsets (owner Q1).

Shared helper coupling (refuter 2 A15): the locate and probe recipe must land
in the I0a shared helper that acc's `_prepare` and the manifest consumer use;
the manifest row (`_row` :2272-2283) must carry the whole-show text or hash
separately from the slice, or acc must become slice-aware in the same change
set. Otherwise emitted rows cannot be reproduced by the consumer.

Expected effect on 2116 (regression re-run, see Q1): rows #1-8 and #9-11
lose all divergences and land as `deferred` (experiments wait for the six
oracles); #12 lands as `rederived` (negative, mutation null, probe matches).
Quarantined 28 -> 17 from this part alone.

### V13 -- locate failures, font_kind, untracked-origin geometry (rows #16-18)

Ours, rederive:

- `target_unlocatable` added to QUARANTINE (:75) and reason_order ordering;
  a LocateError is never labelled `result=exception` and never compared with
  the record's reason; `_compare_probe` skips result/reason/exception_type
  when rederive itself could not locate. Reason-only fallback probe for kind
  in {census, negative} with the uniqueness guard; geometry stays quarantined
  whenever non-null and unlocatable.
- Positional locate fallback (brief-defined, see below) with the A8
  preconditions; `remeasured.locate_method` in {text, positional}.
- `font_kind` from `scene.cap.subtype`; keep `cap.cid` for the advance path.
- `geometry_on_untracked_origin` divergence when the replayed show has
  origin_reliable False and the record carries non-null target geometry.
- Tests: Type0 fixture with empty bfchar destinations recomputes `type0`;
  a LocateError row produces `target_unlocatable` with zero probe
  divergences; a census row with undecodable texttrace locates positionally
  and matches the recorded reason; a row with origin_reliable False and
  non-null geometry diverges; existing test_evidence_rederive.py:1160 stays
  green; tests asserting a `locate` divergence (around :87-100, :208, :661)
  are updated.

Ours, brief v4 plus schema (red-first validator test): `target_bbox_raw`,
`target_bbox_visual`, `expected_origin_visual` become nullable ONLY when
`text_state.before.origin_reliable == false`, with a `limits[]` entry
required; non-null geometry on such a row is a validator violation
`geometry_on_untracked_origin` (gated rev >= 4). M1 gains the positional
branch: when the texttrace unicode at the anchor is U+FFFD or private-use,
take the glyph nearest `show.origin_user * frame.base` (< 0.02 pt) and the
following n glyphs (n = len(decoded_bytes)//unit), one contiguous span, same
font as the show, origin_reliable True; record `locate_method`. `font_kind`
defined as /Subtype-derived; advance_function for a codec-less Type0 =
census only.

Expected effect: #16 stays quarantined with the correct labels
(`target_unlocatable` plus `geometry_on_untracked_origin`); #18 ->
`rederived`; #17 loses `remeasure` but keeps `provenance_unverified` until
I0a. Quarantined 17 -> 16.

### V14 -- canary remeasure (rows #13-15)

Ours, rederive only (brief gets a clarifying note, no rule change): operand
selector per A9 limited to `_old_new_codes`, `_first_change_old` and the K
read in `_judge_experiment`; `canary_changes_shape` divergence for any other
multi-change shape; after-locate anchored on rederive's located before-origin
with the 0.02 pt gate and a positional fallback, plus a separate
`after_text_identity` observation (expected fault on CANARY_FONT /
CANARY_WRONGGLYPH, divergence on experiment and product rows). Tests: a
three-change TC-shaped record remeasures adv_old == adv_new, displacement 0,
no verify_bbox divergence, K_written None; a fixture with a second occurrence
of the replacement 70+ pt away and a glyph-swapped target takes the target's
box; single-change rows unchanged.

Expected effect: #13-15 -> `rederived` (canaries never emit). Quarantined
16 -> 13.

### V15 -- reason_order predicate (rows #19-20)

Ours, rederive plus design doc: move the check after `_Scene` is built;
quarantine only when class in F2_CLASSES, expected_reason ==
tj_multi_item_array AND the derived target is NOT the whole show
(sha256(scene.text) != original_sha256, or byte_range non-null, or mutation
non-null, or kind != negative). Amend design.md:117, :228 and the R3-1 row
:392; keep the positive-base assertion in test_evidence_rederive.py:1021-1028
and add the negative-twin case asserting an empty quarantine. Expected
effect: #19-20 -> `rederived`, emitting as engine_active negatives, SUBJECT
to the X5 hold (Q2). Quarantined 13 -> 11.

### V16 -- provenance and registration (rows #17, #21-28)

Ours, validator (both gated on brief_revision >= 3 so 1114 stays identical):
`relative_path_required` when provenance in {public, local_unrecorded} and
relative_path is null; `slug_not_derived` when source.slug !=
`_slugify(Path(relative_path).stem)` for those provenances (shared helper
with rederive). Ours, docs only this round: ARCHITECTURE quarantine
vocabulary and a PITFALLS entry stating that `before_pdf_mismatch` also means
"source unresolvable" (:866, :891, :898, :900); renaming is deferred (touches
the QUARANTINE pin at test :1756, design.md:117, the brief).

Ours, I0a (owner decision 7): register in public_corpus_sha256.json, with
hashes recomputed from disk by us, not copied from the bundle: isartor
6.3.7 t03-fail-a (644ac66a..., lineage isartor-6-3-7-t03-fail), isartor
6.3.2 t01-fail-a (600d25fc..., lineage isartor-6-3-2-t01-fail), veraPDF
test suite 6-8-3-3-t01-fail-a (b19edaa3..., lineage vera-6-8-3-3-t01-fail),
isartor 6.3.4 t01-fail-d (6c37fb06..., lineage isartor-6-3-4-t01-fail,
shared with the registered -g). Land the manifest with the local_unrecorded
corpora test-colored-background (00640a01...) and test-complexed-layout
(faefb744...), plus the other two brief-listed files after hashing them on
disk, and add the manifest leg to `load_registry` (:205-206) red-first. Keep
the provenance filter in `CorpusRegistry.by_sha` (:151-155).

Next brief paste tells Grok (explicit rules, not corrections except (b)):
(a) local_unrecorded rows carry relative_path; only proprietary/synthetic
null; (b) slug must equal `_slugify(stem)`, citing the vera row; (c) replace
the stale "already registered in the manifest" wording at L152/L220/L269
with "registered by I0a; until then expect quarantined: provenance_unverified,
still remeasured".

Expected effect after I0a: #21-24 -> `rederived`/`deferred`; #17 ->
`rederived` once V13's positional locate lands; #25-28 resolve by sha and are
measured for the first time (#28 may then hit `geometry_on_untracked_origin`).
Quarantined 11 -> 0 to 2.

### Projected 2116 numbers

Before: rederived 12, deferred 15, validator_rejected 8, skipped 1,
quarantined 28. After V12-V15 (no registration): quarantined 11 (9 provenance
plus #16; #17's remeasure cleared but provenance kept), deferred 15 -> about
25, rederived 12 -> about 18. After V16/I0a as well: quarantined 0-2 (#16 by
design, #28 possibly), the rest split between deferred (experiments and
committed rows waiting for I0b oracles) and rederived. validator_rejected 8
(V11 plan rows) and skipped 1 are untouched: only a fresh Grok run under
brief v4 can change them. These are projections from the row-level causes,
not measurements; the re-rederive is the test.

### What the next brief paste must tell Grok (collected)

1. New definitions (contract now says): `original` = target slice,
   `show_text_sha256`, `item_range` = item indices, sub-show locate recipe
   for M0/M1/L702, slice probe plus whole-show second view, `font_kind` by
   /Subtype, geometry null under origin_reliable=false, positional locate
   branch for undecodable texttrace, canary `changes[]` may carry operator
   insertions and `advance` describes the string operand alone,
   local_unrecorded rows carry relative_path.
2. Corrections (Grok deviated): slug must be `_slugify(stem)` (vera row);
   the five dotted veraPDF slugs and the invented `split` variant from V11.
3. Stale text removed: "already registered in the manifest" at
   L152/L220/L269.
4. No Grok rule for the F2/F3 granularity rows, canaries, reason_order or
   the five public provenance rows: those records comply under the new
   definitions.

### Not in V12 scope (explicitly)

- No product change: nothing in the 28 rows is product nondeterminism; the
  three product verdicts in group C are correct and reached before any
  geometry is consumed (binding before geometry: inspect.py:1809-1812,
  plan.py:2076-2082, marked_content.py:418-421).
- No renaming of `before_pdf_mismatch` this round.
- No change to the X5 status of F2R/F2G: measurements only, per owner
  decision 2.

## 4. Questions only the owner can decide

Q1. Revision gating of the new `item_range` / `original` semantics. Option A:
apply to brief_revision >= 3 as well (the v3 brief never defined them; the
only rev-3 rows carrying them are 2116 frontier rows, all written with
index/slice semantics; 1114 and 1713 carry null) so 2116 can be re-rederived
as the regression fixture for V12. Option B: gate on rev >= 4 and treat 2116
as "fresh run, never re-score" like 1803. Recommendation: A for the rederive
reading (it is the only way to prove the fix on real rows) with the emit
hold of Q2, B for ingesting anything from 2116.

Q2. X5 hold mechanism. Clearing the F2R/F2G quarantines plus the reason_order
fix makes three F2R rows and the F2R negative twin emit-eligible after I0b.
Remove F2R/F2G from DEFAULT_PLANNED, or add a `measurement_only` flag that
emit_rows honours? Recommendation: the flag, because the rows must still be
planned, executed and recorded (brief L240-242).

Q3. `font_kind` meaning: /Subtype-derived (recommended; record stays
`type0`, codec-less Type0 is census-only) or capability-derived (then Grok
must write `simple` for a 2-byte CID font and the brief must say so).

Q4. F17 untracked-origin geometry: make the three geometry fields nullable
under origin_reliable=false (schema change, recommended) or keep them
required and accept that they describe a positional anchor the brief forbids
to retry.

Q5. Reason-only fallback probe for census/negative rows that rederive cannot
locate (expected_origin=None): accept such rows as `rederived` evidence with
geometry marked unverifiable, or keep them quarantined until the positional
locate exists? Recommendation: accept only with the uniqueness guard and
only when the record's geometry is null; otherwise quarantine.

Q6. I0a registration list: confirm the four public files and the lineage_id
for the veraPDF test-suite file; note 6c37fb06 adds no second lineage for
F30N; confirm the two remaining local_unrecorded files are to be hashed and
registered now.

Q7. `before_pdf_mismatch` rename to a separate `source_unresolvable` code:
this round (touches brief, design doc, test pin) or deferred (docs only, as
proposed)?

Q8. Product observation worth recording: on r2-F3-bdb495e9-p0-s49-neg1 the
product PREPARED and (in rederive's replay) committed a Tier 1 edit when
asked to replace a whole item with a one-glyph string. That is the engine
working as designed on a whole-show target, but the brief's F3 negatives
will systematically show it; log it as a product observation in TODOS or
ignore?
