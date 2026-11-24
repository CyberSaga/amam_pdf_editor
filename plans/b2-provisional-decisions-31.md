# B2 provisional decisions: the full 31 (recorded 2026-11-25, not executed)

Owner supplied this list; 16 from the B2 build entry (2026-11-23) and 15 from the B2 review fixes entry. None ratified yet. Source: plans/cad-vector-object-editing-handoff.md. Earlier the count read 24 (16 + 8): the review-fix list below has 15.

## B2 build (16)
1. Stored geometry is in page space. The ctm column is the user-space CTM without the frame. O-scan runs with the identity frame.
2. Offsets index the plain concatenation of the streams, no separator. Each stream is lexed alone. Graphics state, the open-path bit and marked-content depth carry across streams. A path split across streams is SPANS_STREAMS. A block whose q and Q sit in different streams is never inert.
3. path_start is the first operand of the record's first construction operator. paint_end ends the paint token. q_end ends the Q token. cm_operand_* covers the first cm, or is -1.
4. EDITABLE = paint is not n, and none of SETS_CLIP, IMPURE, SPANS_STREAMS, IN_OC, CTM_SINGULAR is set. DEGENERATE, CLIPPED and PAGE_ANCHORED stay editable, so delete is allowed. Singular means |det| <= 1e-12.
5. CLIPPED is set by any active clip in scope (W/W*, or text render mode 4-7 at ET), not only by one narrower than the page. This conflicts with design 4.4; the owner ruled it, and the doc now says any clip counts.
6. Closing: h, s, b, b* add a closing segment only when the current point differs from the subpath start. f, F, f*, B, B* add none. A paint with no open path makes no row but still counts as a paint.
7. W/W* set SETS_CLIP and do not make a record IMPURE. Any other non-construction, non-paint operator between construction and paint does.
8. Block inert follows D17 rules 1-3. Comments count as whitespace. Rule 4 is applied by plan_delete through the row flags.
9. PAGE_ANCHORED: any gs in scope, or a colour space set by cs/CS/scn/SCN to a non-device name. A later device colour operator clears it. q/Q restore it.
10. IN_OC is set when an /OC section is open at the paint or at the record's first construction operator. BDC takes its first operand as the tag. EMC with nothing open is SCAN_ERROR.
11. line_width = nominal w (default 1.0) x sqrt(|det| of the paint-time CTM) x frame. NaN after gs until the next w or the restoring Q.
12. bbox is the control polygon, widened outward by one float32 step, not the chords. Chord count uses the Wang formula.
13. Scan errors that refuse the page: Q or EMC below depth 0, unterminated string or hex string or dictionary, malformed or non-finite number, too few operands, operand of the wrong kind. Numbers use float() only.
14. scan_page raises TypeError for bad input types. A missing, non-finite or singular frame is NO_FRAME. Cancel raises VectorScanCancelled. Progress is every 16,384 tokens and at each stream end, ending with (total, total).
15. The streams table is filled with xref = -1 and an empty raw_key. The coordinator rebinds them from the live page.
16. Caps: decoded size is checked before lexing. Paints are counted per paint operator. The chord cap counts chord rows and is checked before each cubic is flattened.

## B2 review fixes (15)
1. Each operand records its stream. A record starts at its first operand in that stream. Cross-stream operands make the row SPANS_STREAMS, and a cm in another stream makes the block non-inert.
2. A stray W stays pending until the next record or a W n. Q does not clear it.
3. One arity table for the listed operators. Wrong counts or kinds refuse the page. Tr must be 0-7. true/false/null are operands of their own kind.
4. Bounds: 4,096 pending operands, 1,000,000 tokens per container, nesting depth 256. Stray closers and non-hex in hex strings refuse. Arrays may span streams; strings may not.
5. Names are #xx-decoded once for /OC and the colour-space names. Offsets stay raw.
6. Dictionary and array state carries across streams between complete tokens.
7. Text: BT/ET are tracked. A path inside BT...ET is IMPURE. Text under Tr 4-7 arms a clip that takes effect at ET. BT 7 Tr ET clips nothing.
8. Schema addition, not in the design body: segments.subpath (int32), the subpath index within its path. The owner must ratify it.
9. Width: line_width = |w| x the larger singular value of the paint-time CTM composed with the frame. No nominal_width column; it is derivable.
10. Geometry must be finite and within float32 range, else SCAN_ERROR. Number tokens are capped at 1 MiB (_MAX_NUMBER_LEN).
11. A degenerate row keeps its transformed first m point as a zero-size bbox.
12. Input is bytes only. The decoded-size cap is charged per stream.
13. cm during construction: measured against MuPDF. The renderer uses the paint-time CTM for the whole path, so the scanner stores user-space points and transforms at paint.
14. Terminal progress event is (total, total), including after an inline-image stop. Cancel is polled in loops and before each cubic. Callback exceptions propagate; the broad except is gone.
15. Class check: nine perturbations plus the 40 grammar scenes. For each EDITABLE row, a cut must leave pixels outside the row's grown bbox unchanged. Limit: overlapping survivors are not compared structurally or by pixel.

## Since
The B2 round-2 fixes superseded parts of this list. The raster outcome check replaced the class check in review item 15. Build decision 5 was settled by the owner. Review item 8 (segments.subpath) still needs ratification (owner delegated the schema design to GPT-6.2-Astra). The B2 round-3 P2s are recorded separately in the handoff.
