# Real-corpus Type0 acceptance tests

## Goal

Add red-first model/engine acceptance coverage for the fourteen already proven
real-PDF text edits: ten HVAC Type0 edits and four ECC `/F2`
`DFKaiShu-SB-Estd-BF` edits. Vector-outline text in CHB and Taoyuan is excluded.

## Modules

- `test_scripts/test_text_commit_real_corpus_acceptance.py` (new)
- `model/text_commit/*` and `model/pdf_model.py` (read-only during this task)
- `scripts/experiment_hvac_font_edits.py` and
  `scripts/experiment_cad_font_edits.py` (read-only source of pinned cases)

## Steps

1. Pin fixture identity and the fourteen target/replacement pairs.
2. Exercise the production `TieredCommitEngine.prepare()` / `commit()` path.
3. Assert the original font resource and CID encoding are reused, text state and
   origin remain stable, and width-changing edits end with TJ compensation.
4. Reopen the saved result and verify decoded text, rendering, target-only
   stream changes, and zero pixel differences outside target masks.
5. Run the focused file with `.venv\Scripts\python.exe -m pytest` and record
   the production red-light failure for the implementation task.

## Decisions

- Local source fixtures are optional in CI, but a present fixture must run and
  must never be skipped.
- The test creates candidates under pytest's temporary directory and never
  changes source PDFs.
- No GUI, production code, documentation, TODO, CHB, or Taoyuan changes.
- Three measured width-changing cases pin their final TJ compensation
  independently: HVAC `Drawing List` (`333`), HVAC revision A→B (`-79`),
  and ECC `[ECC_DWG]`→`ECC-3` (`-500`).

## Dead ends

- The production engine currently refuses all fourteen cases before commit:
  eight at `mc_malformed_pairing`, five at scratch page-fingerprint drift,
  and one reflected-TRM case.  The acceptance tests intentionally remain red
  for the implementation task.
- Full-file execution takes about 108 seconds locally because it runs the
  aggregate prepare diagnostic plus one round-trip case per fixture.  The
  14-case prepare diagnostic alone takes about 27 seconds and is the fastest
  command for implementation feedback.
