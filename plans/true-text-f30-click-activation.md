# F30 click activation: 12 UI-proven simple-font rows become `active`

## Current state and next step
- 2026-11-02. Owner rulings: bind 5 corpora to existing twins, build a MacRoman twin for issue1233, the grow/shrink
  edits must be tested too, no "twin id exists" check.
- Done: 755e7d2 (UI harness strips the subset tag at ui:715/950; the 12 rows `click_reachable`).
- Done: dc12fa0 (the 12 rows `active`, MacRoman twin).
- 2026-11-04 follow-up "UI-run the 16 hit-test rows": all 16 pass every UI phase (env + shipped); 12 go `active` with an
  existing twin; calrgb s0-s3 stay `engine_active` (no twin kind for an unembedded base-14 font with no `/Encoding`).
- 2026-11-04 owner rulings: keep the 12 `active`; calrgb s0-s3 DEFERRED (a twin kind for base-14 without `/Encoding`
  is a separate decision); the 12 get grow/shrink edits too, as on 11-02. Done in the lane: each of the 12 shows
  UI-run with a grow and a shrink edit (env + shipped); 11 rows rewritten to a Tier 1 edit, so all 12 now carry one
  (4 `#grow` incl. the existing minimal-document s7, 8 `#shrink`), 0 kept `#eq`; 6 grows refused
  `growth_region_not_blank` (log). Uncommitted in a lane. Next: the owner's commit word; open follow-ups in TODOS:35
  (Tier 1 twins, calrgb twin kind deferred, preview clipping, two-line selection, 21 one-word rows).

## Goal
The 12 rows the 11-02 real-UI run and the owner's hand run proved (pr4897 s3/s5/s7, basicapi s0, bug1868759 s68/s69,
issue1233 s0/s1, multicolumn s3/s49, bug1946953 s0/s2) move `engine_active -> active`, so the click-path loops and the
UI umbrella run them on every suite.

## Decisions
- One positive per show (`check_unique_per_show`): the 7 grow/shrink shows already hold an `#eq` row, so those rows
  are rewritten to the proven edit (replacement, `expected_tier` 1, `expected_tj_compensation` = the kern the engine
  writes, key variant `#grow`/`#shrink`; precedent `minimal-document/p0/show7#grow`). The 5 eq rows keep their
  replacement. Provenance keeps the rederive batch (the case it came from was the eq variant).
- Twins (verified from the font programs, not the names):
  - bug1868759 TMFNNS+TimesNewRomanPSMT: TrueType, /WinAnsiEncoding, (3,1) only, no post -> `simple_winansi_nopost`.
  - bug1946953 ArialUnicodeMS: symbolic (flags 4), no /Encoding, (1,0) only -> `simple_symbolic_mac10`.
  - multicolumn CMR10/CMBX12: Type1 /FontFile, no /Encoding (built-in vector) -> `simple_type1_builtin`.
  - issue1233 TimesNewRoman,Bold: TrueType, /MacRomanEncoding, (0,3)+(1,0)+(3,1), post 2 -> new kind `macroman`.
  - pr4897 Helvetica-Bold, basicapi Times-Bold: unembedded base-14 /WinAnsiEncoding (F30N) -> the ORACLE twin
    `v-guard-std14` (`stream_storage_fixtures` case a, Helvetica WinAnsi, product path pinned COMMITTED).
- Twins pin Tier 0 only (the registry's target/replacement is width-neutral). Tier 1 on these font structures is
  proven by the real-file rows, which run only where `test_files/` exists (not CI).

## Log
- 2026-11-02: plan opened.
- MacRoman twin: red first (3 frontier-twin tests failed on the unknown kind), then builder kind `macroman`
  (`_KIND_ENCODING`, (1,0)+(3,1) cmaps); observed at HEAD: COMMITTED tier 0, gid 34 (the A outline), both call shapes.
  frontier twins + simple font programs: 206 passed.
- Manifest: the 12 rows `active` with twins; 7 rewritten to grow/shrink (kerns from the 11-02 run: pr4897 s5 +555.999994,
  s7 -555.999994; basicapi s0 +388.999999; bug1868759 s68 +500.0; issue1233 s1 -389.0; multicolumn s3 +443.8;
  bug1946953 s2 -556.0); bug1868759 s69 takes the proven date swap "06/12/2023, 14:21" (still Tier 0, `#eq`).
  The file round-trips byte-identically through `json.dumps(indent=2, ensure_ascii=False)` + CRLF.
  Manifest + public rows + fixture digests: 53 passed.
- PITFALLS: subset-tag trace name; `click_reachable` is a default, not a measurement (+ index).
- Runs: acc 51 passed; click latency 11; UI umbrella for the 6 new corpora 12/12 (env + shipped). The two click-path
  loops decoded every show as Type0 (`decode_show` default): now `font_kind=case.font_kind`; source_run 25, show_commit 16.
- `run_suite.py`: Qt lane 134/134 files (2921 passed); the pure lane first failed to collect (oracle-twins `_MATRIX` had
  no `macroman` row; added `("glyph_name_agl", None)`, oracle twins + wrong-glyph refuter 227 passed); pure lane rerun
  6449 passed, 0 failed. ruff clean.
- 2026-11-04, follow-up: the 16 rows that pass the model hit-test but were never UI-run. Hit-test re-run at 56584a6
  (the acc1104 `reach.py`): 26 active ok, 16 engine_active ok, 21 one word, the same split as 11-02. The UI umbrella
  body has no row selector (`_PAGE_GROUPS` = active + click_reachable), so the rows ran through the 12 rows' shim: a
  scratch test calls `test_ui_commits_every_real_type0_edit_through_the_running_app(spec, page, config, ...)` with a spec
  holding only the target rows, exactly as the manifest has them. 10 page groups x env/shipped: 20 passed, every case
  pass in all 8 phases (select .. second_renderer), minimal-document s7 `#grow` included (Tier 1, +500).
  Twins, from the font programs:
  - artofwar CoronationScot (p4 s0) and bug1946953 s1/s3 (the active rows' xref): TrueType, flags 4, no /Encoding,
    (1,0) only, post 2 -> `simple_symbolic_mac10`.
  - minimal-document CMR10, issue1127 CMBX10, fit11-talk CMTT10: Type1 /FontFile, no /Encoding, a `dup` vector
    (`/Encoding 256 array`, not StandardEncoding) -> `simple_type1_builtin`.
  - verapdf 6-8-3-3 FreeMonoBold: TrueType, /WinAnsiEncoding, no post, flags 262177 (nonsymbolic); (0,3)+(1,0)+(3,1),
    the encoding goes through (3,1) as in bug1868759 -> `simple_winansi_nopost` (the builder names this file).
  - inline-image, isartor 6-3-4 (a descriptor with flags 32 but no FontFile), issue2770 x3: unembedded Helvetica,
    /WinAnsiEncoding -> `v-guard-std14`.
  - calrgb Times-Roman x4: unembedded, NO /Encoding (the font's built-in StandardEncoding). `v-guard-std14` is Helvetica
    /WinAnsiEncoding, so no existing kind covers it (as /MacRomanEncoding needed its own kind): not flipped.
  Red first: `test_true_text_i1_public_rows.py` pins the tracked bug1946953 s1 row; the `ACTIVATED` overlay failed
  (state/click_reachable/twin) before the flip. Manifest: 12 rows `active` (3 fields each, byte-identical round-trip).
  After the flip: public rows + manifest + fixture digests 53 passed; acc 51; source_run 25; show_commit 16; click
  latency 11; UI real corpus file 63 passed (24 new: 8 new page groups x env/shipped/text-box). ruff clean.
- 2026-11-04, owner rulings: keep the 12 `active`; calrgb s0-s3 deferred; grow/shrink edits for the 12 too
  (「變長、變短的編輯也要測到」, as 11-02). Method = the 11-02 one: the engine prepares the edit on the pristine fixture
  (`TieredCommitEngine(max_tier=1)`, the acceptance `_prepare`), the kern it writes becomes the case's
  `expected_tj_compensation`, and the same real-UI shim as the 16-row run drives the umbrella body with one spec per
  (page group, leg) (grow and shrink of one show never share a spec: the umbrella leaves each edit applied). Grow =
  a natural longer text drawn from glyphs the font already shows; shrink = a natural shorter text.
  Results (Tier 1 = every phase pass, select .. second_renderer, env and shipped; the env and shipped saved pages
  render byte-identical; 6x crops of the saved files and the app grabs eyeballed: same face, size, baseline, start x):

  | show | twin | grow | shrink | row now |
  |---|---|---|---|---|
  | artofwar p4 s0 "The Puppet Press  www.puppetpress.com" | symbolic_mac10 | "...Presses..." refused (raster: the rule under the header) | "The Puppet Press  puppetpress.com" T1 -2299.0 | `#shrink` |
  | bug1946953 s1 "Type" | symbolic_mac10 | "Types" refused (vector: table cell border) | "Typ" T1 -556.0 | `#shrink` |
  | bug1946953 s3 "Dist" | symbolic_mac10 | "Dists" refused (vector) | "Dis" T1 -277.0 | `#shrink` |
  | inline-image s0 "Test" | v-guard-std14 | "Tests" T1 +500.0 | "Tes" T1 -277.999997 | `#grow` |
  | isartor 6-3-4 s0 "text with unembedded PDF core font" | v-guard-std14 | "...fonts" T1 +500.0 | "...fon" T1 -278.0 | `#grow` |
  | issue2770 s0 "Plasticoat" | v-guard-std14 | "Plasticoats" refused (image) | "Plastic" T1 -1389.999986 | `#shrink` |
  | issue2770 s1 "950 Winzig Ln" | v-guard-std14 | "950 Winzig Lane" refused (image) | "50 Winzig Ln" T1 -555.999994 | `#shrink` |
  | issue2770 s2 "Lebanon, OH 45036" | v-guard-std14 | "Lebanon, OH 45036." refused (image) | "Lebanon, OH" T1 -3057.999969 | `#shrink` |
  | minimal-document s7 "amet." | type1_builtin | "amet.a" T1 +500.0 (existing row) | "amet" T1 -277.8 | `#grow` (kept) |
  | verapdf 6-8-3-3 s0 "Hello World" | winansi_nopost | "Hello Wordle" T1 +600.0 | "Hello Word" T1 -600.0 | `#shrink` |
  | issue1127 s11 "Kandidat/in:" | type1_builtin | "Kandidat/innen:" T1 +1804.9 | "Kandidat/in" T1 -319.4 | `#grow` |
  | fit11-talk p16 s10 ".appendChild(script)" | type1_builtin | "...(scripts)" refused (vector) | ".append(script)" T1 -2625.0 | `#shrink` |

  Refused = `growth_region_not_blank` at preview in both configs (no token, Apply blocked); that refusal is the
  engine's correct answer there (the zone right of the show is not blank), so no `simple_symbolic_mac10` row carries a
  grow. Choice when both legs pass: grow (it exercises the growth gates), except verapdf, which takes shrink because
  `simple_winansi_nopost` had no shrink row (bug1868759 s68 is `#grow`). A grow candidate outside a subset font's
  glyph set is refused before Tier 1 is judged: FreeMonoBold "Hello Worlds" / "Hello World!" -> `font_widths_incomplete`
  (PITFALLS). Manifest: 11 rows rewritten (key variant, replacement, `expected_tier` 1, the written kern), provenance
  untouched; byte-identical round-trip. Red first: the `test_true_text_i1_public_rows.py` overlay pins bug1946953 s1 as
  `#shrink` and looks the row up by the overlay's key: `KeyError: 'bug1946953/p0/show1#shrink'` before the rewrite.
  After the rewrite: public rows + manifest + fixture digests 53 passed; acc 51; source_run 25; show_commit 16; click
  latency 11; UI real corpus file for the 9 changed/related corpora 27 passed (env + shipped + text-box, the tracked
  manifest rows, no shim). ruff clean; mypy clean.
