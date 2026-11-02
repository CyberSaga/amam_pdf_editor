# F30 click activation: 12 UI-proven simple-font rows become `active`

## Current state and next step
- 2026-11-02. Owner rulings: bind 5 corpora to existing twins, build a MacRoman twin for issue1233, the grow/shrink
  edits must be tested too, no "twin id exists" check.
- Done: 755e7d2 (UI harness strips the subset tag at ui:715/950; the 12 rows `click_reachable`).
- All steps done and green (see log); uncommitted. Next: the owner's commit word.

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
