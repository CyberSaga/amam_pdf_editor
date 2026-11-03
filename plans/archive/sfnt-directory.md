# sfnt table directory: one reader, four rulings

## Current state (update as you go; at most 40 lines)

- Step 1 DONE: this plan, `scripts/sfnt_corpus_scan.py` (`--scan`, `--fingerprint OUT`, `--diff BASE OUT`),
  `test_scripts/sfnt_variants.py`, `test_scripts/test_sfnt.py`, baseline fingerprint of the UNCHANGED readers.
- Baseline fingerprint (4,418 PDFs found, 1,247 with a program, 3,477 programs, 2,198 distinct): R1 `truetype` 2,139,
  `unproven:unreadable` 56, `unproven:post_format` 3; R2 readable 2,180, `None` 18. Two runs are byte-identical.
  Kept OUTSIDE the repo by the orchestrator; regenerate from a checkout before the first reader change (scan ~20 s).
- Pre-change baselines: `test_simple_font_programs.py` 165 passed; `test_text_commit_cid_hex_tj.py` 75 passed.
- Steps 2-5 DONE (full detail in "Log" below): `sfnt.py` added; R2 (step 3) and R1 (step 4) adopt it; R1 releases
  the program (step 5: `cmap.copy`, `_PostNames` with a 255-byte tail, `_reachable_outlines`; `_data`, `_loca_*`,
  `_glyf` gone). Review round applied: hmtx clip `(size - offset) & ~3` (`hmtx_out_of_range` / `hmtx_empty`),
  `loca_format` refusal, one `MAX_FONT_PROGRAM_BYTES`. The 52-byte `head` fixture is padded to 54. `test_sfnt.py` 136+.
- Final corpus diff vs the baseline: exactly 3 R2 results flip, all readable -> None (issue13193 xref 5 and
  issue9262_reduced xref 2: ttcf; issue2537r xref 22: indexToLocFormat 256); R1 identical for all 2,198 programs.
  Gates run green: test_sfnt, test_simple_font_programs 165, test_i1_refute_wrong_glyph 61,
  test_i1_refute_negatives_flip 9, test_glyph_boxes, test_text_commit_cid_hex_tj 75, test_text_commit_click_latency 11,
  test_p4b2_shadow_census 18; ruff clean; mypy Success.
- Step 6 DONE 2026-11-03 (whole-tree gate on the finished tree): `ruff check .` clean, mypy Success (82 files),
  `scripts/run_suite.py` 9593 passed / 0 failed / 0 hung / 0 crashed, VALIDATION.json byte-identical on all 24
  `_evidence_pilot/*_r2` batches, 0952 rederive report identical after masking `remeasured.output_sha256`.
  Plan archived; the open loca_format decision and M2 live in TODOS.md.
- Step 7 docs DONE 2026-11-03: ARCHITECTURE (sfnt paragraph), two PITFALLS entries + index regen, TODOS (items closed,
  loca_format decision and M2 list added). Remaining close-out: `git mv` this plan to `plans/archive/` after step 6.
- OPEN OWNER DECISION: loca_format rule (refuse outside {0, 1} as landed, or FreeType `!= 0` = long loca; needs a
  PDF-route drawing measurement on issue2537r first).
- M2 (a TODO, NOT part of this plan): hmtx absent; hhea absent (FreeType: fatal for 0x00010000), out of range or under 36;
  maxp length 6..31; Type0/CIDFontType2 route for every face-fatal variant; nonzero indexToLocFormat drawing; whether
  the `& ~3` hmtx clip is observable; ttcf shapes beyond one/two members. Each needs a corpus fingerprint diff first.

## Log (moved out of the current-state block 2026-11-03)

- Step 2: `test_sfnt.py` 111 passed, 10 red (reader-level ruling tests: first_in_range, zero_length_glyf,
  out_of_range_first_entry, head_52_and_53, any_short_head, hmtx_offset, hmtx_length_clipped,
  out_of_range_cmap_and_post, ttcf, retention). `sfnt.read_glyph_tables` agreed with R2 on 2,196 of 2,198 distinct
  programs (the 2 differing are the ttcf programs, D3). Fingerprint identical to the baseline (readers untouched).
- Steps 3-4: R2 on sfnt (2 ttcf programs now `None`); R1 `_TrueTypeProgram.__init__` uses `sfnt.read_glyph_tables`,
  cmap/post from directory slots (out of range = absent); `test_sfnt.py` 120 passed, only retention red; R1 fingerprint
  identical for all 2,198.
- Review round (Opus): hmtx clip and refusal (measured: FreeType says "hmtx table missing"); `indexToLocFormat` outside
  {0, 1} refuses (`loca_format`; the loader loads such a face and reads a long loca for any nonzero value); both readers
  bind `_MAX_FONT_PROGRAM_BYTES`. `test_sfnt.py` 136 passed. Corpus: the 2 ttcf programs plus issue2537r.pdf xref 22
  (format 256 on a real LONG loca, 244 bytes for 60 glyphs; R2 used to misread it as short, now `None`; R1 was already
  unreadable). OWNER decision open: refuse (as landed) or read nonzero as long (MuPDF-exact, readable).
- Step 5: `_reachable_outlines` runs at the end of `__init__` (routes of codes 0..255, 0 < gid < num_glyphs) and
  `outline(gid)` reads that dict; `_long_loca` (a bool) stays for `test_sfnt.r1_facts`;
  `test_readers_agree_on_shared_facts` reads the glyf slot from `sfnt.read_glyph_tables`;
  `test_the_truetype_outline_test_equals_number_of_contours` iterates the reachable gids (`symbolic_f100` has none).
  `test_sfnt.py` 121 passed (retention green); R1 fingerprint identical.

## Goal

Two readers walk the same TrueType table directory: `_TrueTypeProgram` in `model/text_commit/simple_font_programs.py`
(R1, simple fonts, behind the `fitz.Font` face gate) and `parse_truetype_glyph_program` in
`model/text_commit/cid_fonts.py` (R2, Type0 fonts, NO loader gate: `fonts.py` builds no face for the Type0 branch).
They disagree on four things. Replace both walks with one stdlib-only `model/text_commit/sfnt.py` that follows the
measured MuPDF/FreeType behaviour, or refuses where that is unmeasured. Release R1's reference to the whole program
after it is read (step 5). TODOS items 6 and 10 close with this plan.

## The four rulings (owner-approved 2026-11-03)

Measured on PyMuPDF 1.27 / MuPDF 1.27 with one seed font, the simple TrueType + WinAnsi route (44 crafted variants,
pixel-exact comparisons). The Type0 route was not measured.

- **D1, repeated tag: the first in-range entry by directory position wins, a zero-length first entry included.**
  MuPDF reads the first entry (not the last, not the lowest file offset, not the sorted slot). A zero-length first
  entry wins and the table is empty (cmap: notdef everywhere; glyf: nothing painted). An out-of-range first entry is
  skipped and the next is used. R1 was already first-wins; R2 was last-wins. Corpus: 0 programs repeat a tag.
- **D2, `head` minimum length 54 (R1 54, R2 52): every `head` entry must be in range and >= 54 bytes.** Length 52 or 53
  (directory length or truly truncated) makes the loader raise "SFNT font table missing"; a losing duplicate shorter
  than 54 (real head first, zero-length head last) refuses the face too. Corpus: head lengths are 54 (2,172 distinct),
  55 (1), 56 (15); none below 54.
- **D3, `ttcf`: refused by both readers.** MuPDF loads face 0 with FILE-ABSOLUTE member offsets, but only the one- and
  two-member shapes were measured and FontFile2 is defined as a TrueType program. R2 used to parse `data[offset:]`,
  resolving member offsets relative to the member: on the two corpus collections (`issue13193`, `issue9262_reduced`)
  it read 0 and 510 glyphs where the file-absolute reading gives 7,614 and 19,398. Those two R2 results become `None`
  (the only corpus change of the whole plan). No manifest, evidence batch or test names either file.
- **D4, a table past the end of the program (R1 refused the program, R2 dropped the table): drop the entry, then
  decide per table.**

  | table out of range | MuPDF | ruling |
  |---|---|---|
  | post, name, OS/2 | ignored, paints normally | absent |
  | hmtx, length past the end | clipped, paints normally | length clipped to `size - offset` |
  | hmtx, offset past the end | face refused | refuse |
  | head, loca | face refused | refuse |
  | glyf | face loads, nothing painted | refuse (nothing provable) |
  | maxp | 0 glyphs, nothing painted | refuse |
  | cmap | no cmaps, every char paints notdef | absent (R1: no code is present) |

  R1 treats an out-of-range cmap or post as ABSENT (MuPDF-exact): a post-less program is nameless and proves only
  through (3,1) plus an outline, so it can newly commit. Corpus: 2 programs have an out-of-range entry, both a bogus
  tag `0x00010000` no reader reads.

Out of scope and unchanged: R1's own cmap and post checks. 41 corpus programs read differently in R1 and R2 today and
39 of them are R1-only cmap/post refusals (22 duplicate cmap subtable, 4 format 2, 4 format 14, 3 post format, 2 subtable
offset, one each of five others); `sfnt.py` must NOT move cmap/post validation into R2 or 39 R2 results flip.

## Design (summary; the full API is in the step-2 module docstring)

`model/text_commit/sfnt.py`, stdlib only (`struct`, `dataclasses`; never fitz, PySide6, fontTools, `cid_fonts` or
`simple_font_programs`): `MAX_FONT_PROGRAM_BYTES`, `HEAD_MIN_LENGTH = 54`, `SfntError(ValueError)` with a `reason`,
`TableSlot(offset, length, copy())`, `SfntDirectory(size, slots, dropped)`, `GlyphTables`, `read_directory`,
`read_glyph_tables`. `read_directory` order: under 12 bytes; `ttcf`; a tag other than `0x00010000` / `true`;
`12 + 16n > size`; walk entries in position order (a `head` entry out of range or under 54 refuses; offset past the end
-> dropped; offset+length past the end -> dropped, except hmtx which is clipped; otherwise `setdefault`); hmtx dropped
with no surviving entry refuses. R1 keeps its cmap subtable walk, post policy, names, outlines, present/proves and both
size caps; R2 keeps the `None` contract, the loca tuple, the `GlyphProgram` evidence fields and its use-site checks.
Step 5: R1 copies cmap (and the post names) instead of closing over the program, precomputes outlines for the gids the
routes can reach (codes 0..255, plus `0xF000 + code` for (3,0)), and drops `_data`, `_loca_*`, `_glyf`. `memoryview`
slices do NOT release the program (see dead ends).

## Tests

`test_scripts/test_sfnt.py` (red first, all driven by `test_scripts/sfnt_variants.py` byte surgery over a simple-font
kind and a Type0 subset program). RED before step 2: `test_first_in_range_entry_wins` (R2 last-wins),
`test_a_zero_length_first_glyf_wins` (R2), `test_an_out_of_range_first_entry_is_skipped` (R1 refuses),
`test_head_52_and_53_refuse` (R2 accepts), `test_any_short_head_entry_refuses` (R1 accepts v1g),
`test_hmtx_offset_past_eof_refuses` (both accept), `test_hmtx_length_past_eof_is_clipped` (R2 drops hmtx),
`test_out_of_range_cmap_and_post_are_absent` (R1 refuses), `test_ttcf_is_refused_by_both` (R2 accepts),
`test_sfnt_is_fitz_and_fonttools_free` (`sfnt.py` does not exist),
`test_a_truetype_proof_keeps_no_reference_to_the_program` (the format-4 closure cell and `_data`).
GREEN from the start (anchors and guards): `test_face_fatal_rules_match_freetype` (25 loader cases against the pinned
`fitz.Font`), `test_readers_agree_on_shared_facts`, `test_edge_inputs_are_refused_by_both` (empty, 11 bytes, numTables
0, directory ending exactly at EOF, directory longer than the file, an OTTO tag).

## Steps and gates

1. Plan, scanner, variants, red tests, baseline fingerprint. Gate: the red set above, every anchor green. DONE.
2. Add `sfnt.py`. Gate: its tests green, `ruff check model/text_commit/sfnt.py`, mypy `model/ utils/`.
3. R2 adopts it (also the 54-byte head fixture, dropping `replace`, the `GlyphProgram` docstring). Gate: the R2 ruling
   tests, then `test_glyph_boxes.py`, `test_text_commit_cid_hex_tj.py`, `test_text_commit_click_latency.py`,
   `test_p4b2_shadow_census.py` (one pytest at a time); corpus `--diff` differs from the baseline in exactly the 2 ttcf
   programs (R2 only).
4. R1 adopts the directory. Gate: the R1 ruling tests, `test_simple_font_programs.py`, `test_i1_refute_wrong_glyph.py`,
   `test_i1_refute_negatives_flip.py`; corpus R1 fingerprint identical to the baseline.
5. R1 releases the program. Gate: the retention test, corpus fingerprint identical, the same three files.
6. Whole-tree gate: `ruff check .`, mypy, `scripts/run_suite.py`, rederive and VALIDATION on the latest batch
   (VALIDATION byte-identical; rederive identical except the per-run `output_sha256`).
7. Docs and close: `docs/ARCHITECTURE.md` (sfnt.py owns the walk; ttcf refused; hmtx clipped or fatal), a PITFALLS
   entry (two readers disagreed four ways; R2 has no loader gate; ttcf member offsets are file-absolute; copies, not
   memoryviews, release a program), index regen, TODOS 6 and 10 closed plus the M2 TODO, `git mv` this plan to
   `plans/archive/`.

## Decisions

- The corpus scanner is a tracked tool (`scripts/sfnt_corpus_scan.py`) so every later gate re-runs on the real corpus.
  It calls the product readers through their public entry points only (no source patching), so it survives the refactor.
- The fingerprint stores R1 `program_kind`, `num_glyphs` and `present` / `proves` for codes 0..255 against `chr(code)`
  (the facade swallows refusal text, and steps 2 to 4 may change message text); R2 stores every `GlyphProgram` field,
  with the `loca` tuple as its length plus a sha256 (a ~20,000-entry list per program is not diffable).
- An existing pin stays valid under every ruling: `test_i1_refute_wrong_glyph.py::test_a_ttcf_container_under_fontfile2_is_unreadable`.
- Expected unchanged: VALIDATION.json and rederive on the latest batch (no manifest row has an affected shape). This is
  a gate, not an assumption.

## Dead ends and traps

- R2's "rebase a ttcf member" (`data[offset:]` plus an offset shift) is wrong, not merely different: it resolves the
  member's table offsets relative to the member, while the spec (and MuPDF) make them file-absolute. The doc comments
  in `ARCHITECTURE.md` and the `GlyphProgram` docstring described the bug as the design.
- Reading face 0 of a collection with file-absolute offsets (the alternative to D3) needs M2 ttcf and Type0 variants
  first, and the ttcf pin would then pass only by accident. Refusing keeps it simple.
- `memoryview` slices of the program pin the underlying buffer; only copies release it.
- An eager outline pass over every gid brings back the per-glyph loop step 12 removed from the click path
  (`cid_fonts.py`, the bulk `struct.unpack_from` of loca). Step 5 precomputes only the gids the routes can reach.
- The scanner of the decision phase patched reader source with `inspect.getsource` string replacement; the tracked
  scanner does not (the patched lines are deleted by steps 2 to 4).
- `head` short-then-long in the old scan controls means `indexToLocFormat` 0 then 1 with two 54-byte heads, not a short
  length; do not confuse it with the D2 shapes.
